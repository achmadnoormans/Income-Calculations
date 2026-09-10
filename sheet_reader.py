import urllib.request
import urllib.parse
import ssl
import csv
import io
import time
from typing import Dict, List, Any, Optional
from config import GVIZ_BASE_URL, PRODUCT_CATALOG, BASIC_SALARIES


def create_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class GoogleSheetReader:
    def __init__(self, cache_ttl_seconds: int = 300):
        self.cache_ttl = cache_ttl_seconds
        self.cached_sheets: Dict[str, Any] = {}
        self.last_fetch_time: Dict[str, float] = {}

    def fetch_sheet_csv(self, sheet_name: str, force_refresh: bool = False) -> str:
        """Fetch raw CSV from Google Spreadsheet GViz endpoint with cache."""
        now = time.time()
        if not force_refresh and sheet_name in self.cached_sheets:
            if now - self.last_fetch_time.get(sheet_name, 0) < self.cache_ttl:
                return self.cached_sheets[sheet_name]

        url = GVIZ_BASE_URL + urllib.parse.quote(sheet_name)
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        ctx = create_ssl_context()

        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                csv_data = resp.read().decode("utf-8")
                self.cached_sheets[sheet_name] = csv_data
                self.last_fetch_time[sheet_name] = now
                return csv_data
        except Exception as e:
            # Check if local fallback file exists
            fallback_filename = sheet_name.replace(" ", "_") + ".csv"
            try:
                with open(fallback_filename, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                raise RuntimeError(f"Gagal mengambil data sheet '{sheet_name}': {e}")

    def get_calculation_records(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Parse rows from the CALCULATION sheet.
        Returns list of agent records with full details.
        """
        csv_text = self.fetch_sheet_csv("CALCULATION", force_refresh=force_refresh)
        reader = csv.reader(io.StringIO(csv_text))
        rows = list(reader)

        if not rows:
            return []

        def parse_num(val: str) -> float:
            if not val:
                return 0.0
            cleaned = val.replace("Rp", "").replace(".", "").replace(",", ".").replace("%", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return 0.0

        def parse_str(val: str) -> str:
            return val.strip()

        records = []
        for row in rows:
            if len(row) < 7:
                continue

            name = parse_str(row[2]) if len(row) > 2 else ""
            if not name or name.lower() in ["nama", "nama agen", "name"]:
                continue
            if any(term in name.lower() for term in ["gaji", "produk", "insentif", "total"]):
                continue

            no = parse_str(row[1]) if len(row) > 1 else ""
            basic_salary = parse_num(row[3]) if len(row) > 3 else 0.0
            total_insentif = parse_num(row[4]) if len(row) > 4 else 0.0
            potongan = parse_num(row[5]) if len(row) > 5 else 0.0
            thp = parse_num(row[6]) if len(row) > 6 else 0.0
            target_pct = parse_str(row[7]) if len(row) > 7 else "0%"
            total_units = int(parse_num(row[8])) if len(row) > 8 else 0

            # Products qty (Cols 9 to 16)
            product_quantities = []
            for c in range(9, 17):
                qty = int(parse_num(row[c])) if c < len(row) else 0
                product_quantities.append(qty)

            # Insentif produk subtotal
            total_insentif_produk = parse_num(row[17]) if len(row) > 17 else 0.0

            # Insentif multiplier subtotal
            total_insentif_multiplier = parse_num(row[29]) if len(row) > 29 else 0.0

            # Insentif pemasangan subtotal
            total_insentif_pemasangan = parse_num(row[38]) if len(row) > 38 else 0.0

            # Determine position
            pos = "PRO"
            if basic_salary == 2500000:
                pos = "OJT"
            elif basic_salary == 4000000:
                pos = "ELITE"

            records.append({
                "no": no,
                "name": name,
                "position": pos,
                "basic_salary": basic_salary,
                "total_insentif": total_insentif,
                "deductions": potongan,
                "take_home_pay": thp,
                "target_pct": target_pct,
                "total_units": total_units,
                "product_quantities": product_quantities,
                "total_insentif_produk": total_insentif_produk,
                "total_insentif_multiplier": total_insentif_multiplier,
                "total_insentif_pemasangan": total_insentif_pemasangan,
            })

        return records

    def find_agent(self, query: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Find an agent record by name (exact, substring, or token match)."""
        records = self.get_calculation_records(force_refresh=force_refresh)
        query = query.lower().strip()
        if not query:
            return None

        # 1. Exact match
        for r in records:
            if r["name"].lower() == query:
                return r

        # 2. Substring match either way
        for r in records:
            r_name = r["name"].lower()
            if query in r_name or r_name in query:
                return r

        # 3. Word token match (e.g. 'Noorman Pratama' -> matches 'Noorman')
        query_words = [w for w in query.split() if len(w) >= 3]
        for r in records:
            r_name = r["name"].lower()
            for w in query_words:
                if w in r_name:
                    return r

        return None

    def refresh_all(self):
        """Force refresh cached sheets."""
        self.cached_sheets.clear()
        self.last_fetch_time.clear()
        self.fetch_sheet_csv("CALCULATION", force_refresh=True)
        self.fetch_sheet_csv("R - GAJI POKOK", force_refresh=True)
        self.fetch_sheet_csv("R - INSENTIF PRODUK", force_refresh=True)
        self.fetch_sheet_csv("R - INSENTIF PEMASANGAN", force_refresh=True)
