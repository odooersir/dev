import requests, json
from bs4 import BeautifulSoup

# لینک API به GTIN → ریدایرکت به صفحه محصول
url = "https://api.qogita.com/variants/link/0034285642129/"
session = requests.Session()
resp = session.get(url, allow_redirects=True)
final_url = resp.url

html = session.get(final_url).text
soup = BeautifulSoup(html, "html.parser")

# استخراج برند از JSON-LD
brand = None
for tag in soup.find_all("script", type="application/ld+json"):
    try:
        data = json.loads(tag.string)
        if isinstance(data, dict) and "brand" in data:
            brand_data = data["brand"]
            brand = brand_data.get("name") if isinstance(brand_data, dict) else brand_data
            if brand:
                break
    except Exception:
        continue
if not brand:
    link = soup.find("a", href=lambda x: x and x.startswith("/brands/") and x != "/brands/")
    if link:
        brand = link.text.strip()

# استخراج اطلاعات فنی
technical_details = {}
table = soup.find("table")
if table:
    for tr in table.find_all("tr"):
        td = tr.find_all("td")
        if len(td) == 2:
            k = td[0].get_text(strip=True)
            v = td[1].get_text(strip=True)
            technical_details[k] = v

# استخراج فقط تصاویر داخل گالری اصلی
gallery_div = soup.find("div", class_="flex grow flex-col gap-2")
image_urls = []
if gallery_div:
    for img in gallery_div.find_all("img"):
        src = img.get("src")
        if src and "static.prod.qogita.com/files/images/variants" in src:
            clean = src.split("format=auto/")[-1]
            if clean not in image_urls:
                image_urls.append(clean)

# چاپ خروجی
print("Brand:", brand)
print("\nTechnical Details:")
for k, v in technical_details.items():
    print(f"  {k}: {v}")

print("\nGallery Images:")
for i, u in enumerate(image_urls, 1):
    print(f"  {i}. {u}")
