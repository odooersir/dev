"""
SBS AI provider
===============
A thin, swappable layer between the extraction logic and whatever model is
actually running. Ollama exposes an Anthropic-compatible Messages API, so the
same `anthropic` SDK talks to both a LOCAL Ollama server and a CLOUD provider -
only base_url / api_key / model differ, and those come from Settings.

Design rules (must not break):
  * Never raise into the import flow. Any failure -> return None, and the caller
    keeps its regex result. Import must succeed even if AI is down/slow.
  * Honor a hard timeout so a slow local model can't stall an import.
  * Respect the master switch: if AI is disabled, is_enabled() is False and no
    network call is ever made.

This module has no Odoo model; it's a helper instantiated from env.
"""
import json
import logging

_logger = logging.getLogger(__name__)

try:
    import anthropic
    _HAS_ANTHROPIC = True
except Exception:                      # library not installed
    _HAS_ANTHROPIC = False


class SbsAIProvider:
    """Wraps one chat call to an Anthropic-compatible endpoint (Ollama/cloud)."""

    def __init__(self, env):
        self.env = env
        icp = env['ir.config_parameter'].sudo()
        self.enabled = icp.get_param('oe_sbs.ai_enabled') in ('True', 'true', '1', True)
        self.base_url = (icp.get_param('oe_sbs.ai_base_url') or '').strip() or None
        self.model = (icp.get_param('oe_sbs.ai_model') or 'qwen2.5:3b').strip()
        self.api_key = (icp.get_param('oe_sbs.ai_api_key') or 'ollama').strip()
        try:
            self.timeout = int(icp.get_param('oe_sbs.ai_timeout') or 15)
        except (TypeError, ValueError):
            self.timeout = 15
        self.for_metadata = icp.get_param('oe_sbs.ai_for_metadata') in ('True', 'true', '1', True)
        self.for_mapping = icp.get_param('oe_sbs.ai_for_mapping') in ('True', 'true', '1', True)

    # ---- capability checks -------------------------------------------------
    def is_enabled(self):
        """True only if the library is present, the switch is on, and we have a
        model to call. Callers should gate every AI use on this."""
        return bool(_HAS_ANTHROPIC and self.enabled and self.model)

    def metadata_enabled(self):
        return self.is_enabled() and self.for_metadata

    def mapping_enabled(self):
        return self.is_enabled() and self.for_mapping

    def has_library(self):
        """Whether the 'anthropic' SDK is importable on this server."""
        return _HAS_ANTHROPIC

    def why_disabled(self):
        """Human-readable reason AI isn't running, for the log. Returns '' when
        everything needed is in place."""
        if not _HAS_ANTHROPIC:
            return ("the 'anthropic' python package is not installed on the "
                    "Odoo server (run: pip install anthropic)")
        if not self.enabled:
            return "the master switch 'Enable AI Assist' is off in Settings"
        if not self.model:
            return "no model name is set in Settings"
        if not self.for_metadata:
            return "'AI for Metadata Extraction' is unticked in Settings"
        return ""

    # ---- the single low-level call ----------------------------------------
    def chat_json(self, system, user, max_tokens=1024):
        """
        Send one prompt and parse the reply as JSON. Returns a dict/list on
        success, or None on ANY problem (disabled, timeout, bad JSON, network).
        The model is instructed to answer with JSON only; we still strip stray
        markdown fences before parsing.
        """
        if not self.is_enabled():
            return None
        if not _HAS_ANTHROPIC:
            _logger.warning(
                "SBS AI: the 'anthropic' package is not installed - "
                "run 'pip install anthropic' to enable AI assist")
            return None
        import time
        t0 = time.time()
        try:
            client_kwargs = {
                'api_key': self.api_key,
                'timeout': self.timeout,
                # The SDK retries twice by default, which multiplies wall time
                # far past our budget (a 15s timeout became 112s). Single
                # attempt only: if the model is slow, we fall back to regex.
                'max_retries': 0,
            }
            if self.base_url:
                client_kwargs['base_url'] = self.base_url
            client = anthropic.Anthropic(**client_kwargs)
            resp = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{'role': 'user', 'content': user}],
            )
            text = self._text_of(resp)
            elapsed = time.time() - t0
            if not text:
                _logger.warning("SBS AI: empty reply from %s (%.1fs)",
                                self.model, elapsed)
                return None
            _logger.warning("SBS AI: %s replied in %.1fs (%d chars)",
                         self.model, elapsed, len(text))
            # the raw reply is what you need when the guard rejects everything
            _logger.warning("SBS AI raw reply: %s", text)
            parsed = self._parse_json(text)
            if parsed is None:
                _logger.warning("SBS AI: reply was not valid JSON - discarded")
            return parsed
        except Exception as e:
            # includes timeouts, connection errors, API errors - never propagate
            _logger.warning("SBS AI call failed after %.1fs (%s at %s): %s",
                            time.time() - t0, self.model,
                            self.base_url or 'default', e)
            return None

    # ---- helpers -----------------------------------------------------------
    @staticmethod
    def _text_of(resp):
        """Concatenate the text blocks of an Anthropic-style response."""
        try:
            parts = []
            for block in (resp.content or []):
                t = getattr(block, 'text', None)
                if t:
                    parts.append(t)
            return "\n".join(parts).strip()
        except Exception:
            return ""

    @staticmethod
    def _parse_json(text):
        """Parse JSON, tolerating ```json fences or leading/trailing prose."""
        s = text.strip()
        # strip code fences
        if s.startswith("```"):
            s = s.strip('`')
            # after stripping backticks a leading 'json' may remain
            if s[:4].lower() == 'json':
                s = s[4:]
            s = s.strip()
        # if there's surrounding prose, grab the first {...} or [...] block
        try:
            return json.loads(s)
        except Exception:
            pass
        for opener, closer in (('{', '}'), ('[', ']')):
            i, j = s.find(opener), s.rfind(closer)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(s[i:j + 1])
                except Exception:
                    continue
        return None
