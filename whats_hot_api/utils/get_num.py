def parse_chinese_number(chinese_number: str) -> float:
    units = {"亿": 1e8, "万": 1e4, "千": 1e3, "百": 1e2}
    for unit, multiplier in units.items():
        if unit in chinese_number:
            try:
                number_part = float(chinese_number.replace(unit, ""))
                return number_part * multiplier
            except ValueError:
                break
    try:
        return float(chinese_number)
    except ValueError:
        return 0
