"""Small exact-model catalog of manufacturer-published specifications."""
import re
import unicodedata
from urllib.parse import urlencode, urlsplit


def model_key(name):
    text = unicodedata.normalize("NFKC", name).casefold().replace("+", " plus ")
    return re.sub(r"[^\w]", "", text)


def safe_source(url):
    if not isinstance(url, str) or any(char.isspace() for char in url):
        return False
    try:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None
    except ValueError:
        return False


def official_image_url(image, source):
    if not safe_source(image) or not safe_source(source):
        return False
    image_host, source_host = (urlsplit(url).hostname.lower() for url in (image, source))
    official_hosts = {
        "apple.com": ("apple.com", "apple-dns.net"),
        "google.com": ("google.com", "googleusercontent.com", "gstatic.com"),
        "samsung.com": ("samsung.com", "samsungmobilepress.com"),
        "samsungmobilepress.com": ("samsungmobilepress.com", "samsung.com"),
        "rokid.com": ("rokid.com",),
        "evenrealities.com": ("evenrealities.com", "cdn.sanity.io"),
        "mi.com": ("mi.com", "mi-img.com"),
        "huawei.com": ("huawei.com",),
        "oppo.com": ("oppo.com",),
        "vivo.com": ("vivo.com",),
    }
    disallowed = ("youtube.com", "youtu.be", "ytimg.com", "gsmarena.com")
    matches = lambda host, domain: host == domain or host.endswith("." + domain)
    if any(matches(image_host, domain) or matches(source_host, domain) for domain in disallowed):
        return False
    allowed = next((hosts for domain, hosts in official_hosts.items() if matches(source_host, domain)), (source_host,))
    return any(matches(image_host, domain) for domain in allowed)


CATALOG = {
    "Pixel 10 Pro": {
        "manufacturer": "Google Store · 미국",
        "url": "https://store.google.com/us/product/pixel_10_pro_specs?hl=en-US",
        "image": "https://lh3.googleusercontent.com/cUnl8qDLSpzTlH9_9fIEpNHq8EiVH-JwF-r0FPGha83zS26d0FO4LYUxYDU-k3CO6VDt9pyMOHWXiSvvFcenGccNM5B1L8TVO-2OtA=w1000-rj-sc0xffffffff",
        "fields": {"디스플레이": "6.3인치 LTPO OLED", "해상도": "1280 × 2856", "주사율": "1–120 Hz",
                   "밝기": "HDR 최대 2,200니트 · 피크 최대 3,300니트", "프로세서": "Google Tensor G5",
                   "배터리": "4,870 mAh (일반 용량)"},
    },
    "Galaxy S26 Ultra": {
        "manufacturer": "삼성전자 뉴스룸 · 영국",
        "url": "https://news.samsung.com/uk/samsung-unveils-galaxy-s26-series-the-most-intuitive-galaxy-ai-phone-yet",
        "image": "https://images.samsung.com/is/image/samsung/assets/us/smartphones/galaxy-s26-ultra/images/galaxy-s26-ultra-features-kv-1.jpg",
        "fields": {"디스플레이": "6.9인치 Dynamic AMOLED 2X", "해상도": "QHD+", "주사율": "1–120 Hz",
                   "프로세서": "Snapdragon 8 Elite Gen 5 for Galaxy", "배터리": "5,000 mAh (일반 용량)", "무게": "214 g"},
    },
    "iPhone 18 Pro": {
        "manufacturer": "Apple · 미국",
        "url": "https://www.apple.com/iphone-18-pro/specs/",
        "image": "https://www.apple.com/v/iphone-18-pro/e/images/meta/iphone-18-pro_overview__bl9no3txkonm_og.png",
        "fields": {"디스플레이": "6.3인치 OLED", "해상도": "2622 × 1206", "주사율": "가변 최대 120 Hz",
                   "밝기": "HDR 피크 1,600니트 · 야외 피크 3,000니트", "프로세서": "A20 Pro", "무게": "211 g"},
    },
    "Rokid Glasses": {
        "manufacturer": "Rokid 고객 지원",
        "url": "https://global.rokid.com/pages/faq",
        "image": "https://global.rokid.com/cdn/shop/files/001_8c854eae-1297-4a66-a5bc-808f5e127dfc.jpg?v=1786429759",
        "fields": {"디스플레이": "Micro LED · 회절 웨이브가이드", "해상도": "480 × 640", "시야각": "30°",
                   "밝기": "아이박스 1,500니트", "배터리": "210 mAh", "무게": "약 49 g"},
    },
    "Even G2": {
        "manufacturer": "Even Realities 고객 지원",
        "url": "https://support.evenrealities.com/hc/en-us/articles/13499229138959-Specs",
        "image": "https://cdn.sanity.io/images/wfyhg2qw/production/fa29f360026bf5c4e080b217180e646d580402f3-1200x630.jpg",
        "fields": {"디스플레이": "녹색 Micro LED · 양안 웨이브가이드", "해상도": "640 × 350",
                   "시야각": "27.5°", "주사율": "60 Hz", "밝기": "1,200니트 (제조사 표기)", "배터리": "안경 192 mAh"},
    },
}
_MODELS = {model_key(name): name for name in CATALOG}
_MODELS.update({model_key(alias): name for alias, name in {
    "Google Pixel 10 Pro": "Pixel 10 Pro", "구글 픽셀 10 프로": "Pixel 10 Pro", "픽셀 10 프로": "Pixel 10 Pro",
    "Samsung Galaxy S26 Ultra": "Galaxy S26 Ultra", "갤럭시 S26 울트라": "Galaxy S26 Ultra",
    "Apple iPhone 18 Pro": "iPhone 18 Pro", "아이폰 18 프로": "iPhone 18 Pro",
    "Even Realities G2": "Even G2", "로키드 글라스": "Rokid Glasses",
}.items()})


def resolve_specs(product, custom=None):
    catalog = CATALOG.get(_MODELS.get(model_key(product)))
    if custom and isinstance(custom.get("text"), str) and custom["text"].strip() and safe_source(custom.get("url")):
        host = urlsplit(custom["url"]).hostname.lower()
        source = "GSMArena · 사용자 등록 참고 자료" if host == "gsmarena.com" or host.endswith(".gsmarena.com") else "사용자 등록 사양"
        fields = {}
        unstructured = []
        for line in custom["text"].splitlines():
            label, separator, value = line.partition(":")
            if separator and label.strip() and value.strip():
                fields[label.strip()] = value.strip()
            elif line.strip():
                unstructured.append(line)
        image = custom.get("image", "")
        if not official_image_url(image, custom["url"]):
            image = catalog.get("image", "") if catalog else ""
        return {"fields": fields, "text": "\n".join(unstructured), "source": source, "url": custom["url"], "image": image}
    if catalog:
        return {"fields": catalog["fields"], "source": catalog["manufacturer"], "url": catalog["url"],
                "official": True, "image": catalog.get("image", "")}
    return None


def manufacturer_search_url(product):
    families = [
        (r"iphone|ipad|macbook|apple watch|아이폰|아이패드|맥북|애플워치", "apple.com"),
        (r"galaxy|samsung|갤럭시|삼성", "samsung.com"),
        (r"pixel|픽셀", "store.google.com"),
        (r"huawei|화웨이", "consumer.huawei.com"),
        (r"oppo|오포", "oppo.com"),
        (r"vivo|비보", "vivo.com"),
        (r"xiaomi|redmi|샤오미|레드미", "mi.com"),
        (r"rokid|로키드", "global.rokid.com"),
        (r"\beven\b", "evenrealities.com"),
    ]
    domain = next((site for pattern, site in families if re.search(pattern, product, re.I)), None)
    query = product + (" specifications site:" + domain if domain else " manufacturer official specifications")
    return "https://www.google.com/search?" + urlencode({"q": query})
