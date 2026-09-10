from typing import Dict, List, Any, Optional
from config import PRODUCT_CATALOG, BASIC_SALARIES, INSTALLATION_TIERS, STANDARD_TARGETS


def format_rupiah(amount: float) -> str:
    """Format numeric amount into Indonesian Rupiah format e.g. Rp 3.500.000"""
    if amount == 0:
        return "Rp 0"
    negative = amount < 0
    amount = abs(amount)
    formatted = f"{int(amount):,}".replace(",", ".")
    prefix = "-Rp " if negative else "Rp "
    return f"{prefix}{formatted}"


class SalaryCalculator:
    def __init__(self,
                 product_catalog: Optional[List[Dict[str, Any]]] = None,
                 basic_salaries: Optional[Dict[str, int]] = None,
                 installation_tiers: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.catalog = product_catalog or PRODUCT_CATALOG
        self.basic_salaries = basic_salaries or BASIC_SALARIES
        self.installation_tiers = installation_tiers or INSTALLATION_TIERS

    def get_multiplier(self, position: str, total_units: int) -> float:
        """Get the incentive multiplier based on position and total units sold."""
        pos = position.upper()
        if pos == "OJT" or total_units <= 0:
            return 0.0

        tiers = self.installation_tiers.get(pos, self.installation_tiers.get("PRO", []))
        for t in tiers:
            if t["min"] <= total_units <= t["max"]:
                return float(t["multiplier"])
        return 0.0

    def calculate_installation_incentive(self, position: str, total_units: int) -> Dict[str, Any]:
        """
        Calculate progressive slab tier installation incentive.
        Returns total and breakdown per tier.
        """
        pos = position.upper()
        tiers = self.installation_tiers.get(pos, self.installation_tiers.get("PRO", []))

        total_amount = 0
        rem_units = total_units
        tier_details = []

        for t in tiers:
            min_u = t["min"]
            max_u = t["max"]
            rate = t["rate"]
            label = t.get("label", f"{min_u} s.d {max_u}")

            cap = max_u - min_u + 1
            units_in_slab = max(0, min(rem_units, cap))
            slab_subtotal = units_in_slab * rate

            tier_details.append({
                "label": label,
                "units": units_in_slab,
                "rate": rate,
                "subtotal": slab_subtotal
            })

            total_amount += slab_subtotal
            rem_units -= units_in_slab

        return {
            "total": total_amount,
            "tiers": tier_details
        }

    def calculate(self,
                  position: str,
                  product_quantities: List[int],
                  deductions: float = 0.0,
                  agent_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute full salary and incentive calculation.
        
        Args:
            position: 'OJT', 'PRO', or 'ELITE'
            product_quantities: list of 8 ints corresponding to PRODUCT_CATALOG
            deductions: any deduction / potongan
            agent_name: optional name of the SA
        """
        pos = position.upper()
        if pos not in self.basic_salaries:
            pos = "PRO"

        basic_salary = self.basic_salaries.get(pos, 3500000)

        # Pad product quantities if needed
        quantities = list(product_quantities)
        while len(quantities) < len(self.catalog):
            quantities.append(0)

        total_units = sum(quantities)

        # 1. Insentif Produk
        product_breakdown = []
        total_insentif_produk = 0
        total_spesial_insentif = 0

        for idx, item in enumerate(self.catalog):
            qty = quantities[idx] if idx < len(quantities) else 0
            rate = item["rate"]
            special_rate = item.get("special_rate", 0)

            subtotal_reg = qty * rate
            subtotal_spc = qty * special_rate

            total_insentif_produk += subtotal_reg
            total_spesial_insentif += subtotal_spc

            product_breakdown.append({
                "id": item["id"],
                "name": item["name"],
                "type": item["type"],
                "label": item.get("label", item["name"]),
                "qty": qty,
                "rate": rate,
                "special_rate": special_rate,
                "subtotal_reg": subtotal_reg,
                "subtotal_spc": subtotal_spc
            })

        # 2. Multiplier & Insentif Multiplier
        multiplier = self.get_multiplier(pos, total_units)
        insentif_multiplier = total_insentif_produk * multiplier
        
        # Per item multiplier breakdown
        multiplier_breakdown = []
        for p in product_breakdown:
            p_mult_val = p["subtotal_reg"] * multiplier
            multiplier_breakdown.append({
                "label": p["label"],
                "qty": p["qty"],
                "subtotal": p_mult_val
            })

        # 3. Insentif Pemasangan (Progressive slabs)
        pemasangan_result = self.calculate_installation_incentive(pos, total_units)
        total_insentif_pemasangan = pemasangan_result["total"]

        # 4. Total Insentif
        total_insentif = (
            total_insentif_produk +
            total_spesial_insentif +
            insentif_multiplier +
            total_insentif_pemasangan
        )

        # 5. Take Home Pay
        take_home_pay = basic_salary + total_insentif - deductions

        # 6. Target & Achievement %
        target_units = STANDARD_TARGETS.get(pos, 12)
        achievement_pct = (total_units / target_units * 100.0) if target_units > 0 else 0.0

        return {
            "name": agent_name or "Sales Agent",
            "position": pos,
            "basic_salary": basic_salary,
            "deductions": deductions,
            "total_units": total_units,
            "target_units": target_units,
            "achievement_pct": achievement_pct,
            "total_insentif_produk": total_insentif_produk,
            "total_spesial_insentif": total_spesial_insentif,
            "multiplier": multiplier,
            "total_insentif_multiplier": insentif_multiplier,
            "total_insentif_pemasangan": total_insentif_pemasangan,
            "total_insentif": total_insentif,
            "take_home_pay": take_home_pay,
            "products": product_breakdown,
            "pemasangan_tiers": pemasangan_result["tiers"],
            "multiplier_breakdown": multiplier_breakdown
        }

    def format_telegram_report(self, res: Dict[str, Any]) -> str:
        """Format the result into a clean, aesthetic Telegram Markdown slip."""
        name = res["name"]
        pos = res["position"]
        units = res["total_units"]
        ach_pct = res["achievement_pct"]
        target = res["target_units"]

        lines = [
            f"📊 *SLIP ESTIMASI GAJI & INSENTIF XL SATU*",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"👤 *Nama SA* : {name}",
            f"🏷️ *Posisi*  : {pos}",
            f"🎯 *Target*  : {units} / {target} Unit ({ach_pct:.1f}%)",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💵 *Gaji Pokok* : `{format_rupiah(res['basic_salary'])}`",
            "",
            f"📦 *1. Insentif Produk Reguler*",
        ]

        active_products = [p for p in res["products"] if p["qty"] > 0]
        if active_products:
            for p in active_products:
                lines.append(f"  • {p['label']} ({p['qty']} unit @ {format_rupiah(p['rate'])}) : `{format_rupiah(p['subtotal_reg'])}`")
            lines.append(f"  ➡️ *Subtotal Insentif Produk*: `{format_rupiah(res['total_insentif_produk'])}`")
        else:
            lines.append(f"  • _Belum ada penjualan produk_ : `Rp 0`")

        if res["total_spesial_insentif"] > 0:
            lines.append("")
            lines.append(f"⭐ *2. Spesial Insentif*")
            for p in active_products:
                if p["subtotal_spc"] > 0:
                    lines.append(f"  • {p['label']} ({p['qty']} unit @ {format_rupiah(p['special_rate'])}) : `{format_rupiah(p['subtotal_spc'])}`")
            lines.append(f"  ➡️ *Subtotal Spesial Insentif*: `{format_rupiah(res['total_spesial_insentif'])}`")

        lines.append("")
        lines.append(f"⚡ *3. Insentif Multiplier ({res['multiplier']}x)*")
        if res["multiplier"] > 0:
            for p in res["products"]:
                if p["qty"] > 0 and p["rate"] > 0:
                    p_sub = p["subtotal_reg"]
                    p_mult = p_sub * res["multiplier"]
                    lines.append(f"  • {p['label']} : `{format_rupiah(p_sub)}` × `{res['multiplier']}x` = `{format_rupiah(p_mult)}`")
            lines.append(f"  ➡️ *Subtotal Multiplier*: `{format_rupiah(res['total_insentif_multiplier'])}`")
        else:
            lines.append(f"  • _Belum mencapai batas minimum multiplier (min. 7 unit)_ : `Rp 0`")

        lines.append("")
        lines.append(f"🛠️ *4. Insentif Pemasangan (Progresif)*")
        active_tiers = [t for t in res["pemasangan_tiers"] if t["units"] > 0]
        if active_tiers:
            for t in active_tiers:
                lines.append(f"  • Tier {t['label']} : {t['units']} unit × {format_rupiah(t['rate'])} = `{format_rupiah(t['subtotal'])}`")
            lines.append(f"  ➡️ *Subtotal Pemasangan*: `{format_rupiah(res['total_insentif_pemasangan'])}`")
        else:
            lines.append(f"  • _0 unit terpasang_ : `Rp 0`")

        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"💰 *TOTAL INSENTIF* : `{format_rupiah(res['total_insentif'])}`")
        if res["deductions"] > 0:
            lines.append(f"✂️ *Potongan*       : `-{format_rupiah(res['deductions'])}`")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🏆 *TAKE HOME PAY*  : *{format_rupiah(res['take_home_pay'])}*")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(lines)
