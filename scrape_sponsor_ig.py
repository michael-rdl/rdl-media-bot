"""
Find Instagram handles for sponsors by searching the web.
Uses DuckDuckGo HTML search to find instagram.com links.
"""
import re
import time
import psycopg2
import requests
from urllib.parse import unquote

DB = dict(host="192.168.1.82", port=5432, dbname="media_bot", user="postgres", password="postgres")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Well-known brands where we already know the handle
KNOWN_HANDLES = {
    "wisefab": "wisefab",
    "bc racing": "bcracing_na",
    "radium engineering": "radiumengineering",
    "feal suspension": "fealsuspension",
    "gt radial": "gtradial_usa",
    "fuelab": "fuelab",
    "link ecu": "linkecu",
    "sabelt": "sabelt_official",
    "advanced clutch technology": "actclutch",
    "ignite racing fuel": "igniteracingfuel",
    "magnuson superchargers": "magnusonsuperchargers",
    "kenda tire": "kendatire",
    "kenda tires": "kendatire",
    "nrg": "nrginnovations",
    "nrg innovations": "nrginnovations",
    "konig": "konigwheelsusa",
    "antigravity batteries": "antigravitybatteries",
    "act clutch": "actclutch",
    "kumho tire": "kumhotireusa",
    "wilwood": "wilwooddiscbrakes",
    "wilwood brakes": "wilwooddiscbrakes",
    "katana wheels": "katanawheels",
    "kansei wheels": "kanseiwheels",
    "simpson": "simpsonraceproducts",
    "sparco": "sparcoofficial",
    "clutch masters": "clutchmasters",
    "ecu master": "ecumaster_official",
    "ford racing": "fordperformance",
    "holley performance": "holleyperformance",
    "deatschwerks": "deatschwerks",
    "rtr vehicles": "rtrvehicles",
    "mobil 1": "mobil1",
    "optima batteries": "optimabatteries",
    "enjuku racing": "enjukuracing",
    "haltech": "haltech",
    "swift springs": "swiftsprings",
    "motul oils": "motul",
    "motul": "motul",
    "k&n": "knfilters",
    "k&amp;n": "knfilters",
    "moza racing": "mozaracing",
    "awe tuning": "aaborexhaust",
    "rugged radio": "ruggedradios",
    "st suspensions": "stsuspensions",
    "turn14 distribution": "turn14",
    "garrett turbo": "garrettmotion",
    "garrett": "garrettmotion",
    "brembo": "baborexhaust",
    "mishimoto": "mishimoto",
    "borla exhaust": "borlaexhaust",
    "recaro": "recarogaming",
    "bride": "bride_japan",
    "yokohama": "yokohamatire",
    "toyo tires": "toyotires",
    "greddy": "greddyperformance",
    "hks": "haborksusa",
    "rays": "raysmsc",
    "enkei": "enkeiwheels",
    "cusco": "cusco_japan",
    "defi": "defi_link",
    "toyota": "toyota",
    "ford": "ford",
    "bmw": "bmw",
    "nissan": "nissan",
    "hyundai": "hyundai",
    "subaru": "subaru_usa",
    "chevrolet": "chevrolet",
    "volk racing": "raysmsc",
    "aem": "aaboremintakes",
    "big duck club": "bigduckclub",
    "fun-haver": "funhaver",
    "tire agent": "tireagent",
    "cage kits": "cage_kits",
    "2f performance": "2fperformance",
    "supertech": "supertechperformance",
    "super tech": "supertechperformance",
    "crower cams": "crowercams",
    "crower": "crowercams",
    "derale": "deraleperformance",
    "sikky": "sikkymfg",
    "ignite": "igniteracingfuel",
    "fuel lab": "fuelab",
    "shell v-power nitro+ premium gasoline": "shell",
    "a&#x27;pexi": "aborpexi_usa",
}


def search_instagram(name):
    """Search DuckDuckGo for the sponsor's Instagram."""
    query = f"{name} instagram official"
    try:
        resp = SESSION.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        ig_matches = re.findall(
            r'instagram\.com/([A-Za-z0-9_.]+)',
            resp.text,
        )
        if ig_matches:
            handles = [h.lower().rstrip(".") for h in ig_matches
                       if h.lower() not in ("p", "reel", "stories", "explore", "accounts", "directory")]
            if handles:
                return handles[0]
    except Exception:
        pass
    return None


def main():
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT name FROM pipeline_sponsor
        WHERE instagram = '' OR instagram IS NULL
        ORDER BY name
    """)
    sponsor_names = [r[0] for r in cur.fetchall()]

    print(f"Searching for Instagram handles for {len(sponsor_names)} unique sponsors...\n")

    found = 0
    not_found = 0
    known_used = 0

    for name in sponsor_names:
        normalized = name.lower().strip()

        # Check known handles first
        handle = KNOWN_HANDLES.get(normalized)
        if handle:
            cur.execute(
                "UPDATE pipeline_sponsor SET instagram = %s WHERE name = %s",
                (handle, name),
            )
            print(f"  [KNOWN] {name}: @{handle}")
            known_used += 1
            found += 1
            continue

        # Search the web
        handle = search_instagram(name)
        if handle:
            cur.execute(
                "UPDATE pipeline_sponsor SET instagram = %s WHERE name = %s",
                (handle, name),
            )
            print(f"  [FOUND] {name}: @{handle}")
            found += 1
        else:
            print(f"  [MISS]  {name}")
            not_found += 1

        time.sleep(1.0)  # rate limit

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    print(f"Known: {known_used}")
    print(f"Found via search: {found - known_used}")
    print(f"Not found: {not_found}")
    print(f"Total updated: {found}")


if __name__ == "__main__":
    main()
