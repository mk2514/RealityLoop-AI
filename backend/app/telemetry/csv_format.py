import csv


DELIMITERS = (",", ";", "\t", "|")


def detect_csv_dialect(sample: str) -> csv.Dialect:
    first_line = next((line for line in sample.splitlines() if line.strip()), "")
    if not first_line:
        raise ValueError("CSV must contain a header row.")
    try:
        return csv.Sniffer().sniff(first_line, delimiters="".join(DELIMITERS))
    except csv.Error:
        counts = {delimiter: first_line.count(delimiter) for delimiter in DELIMITERS}
        highest = max(counts.values(), default=0)
        candidates = [
            delimiter for delimiter, count in counts.items() if count == highest
        ]
        if highest == 0 or len(candidates) != 1:
            raise ValueError(
                "Could not determine CSV delimiter. Use comma, semicolon, tab or pipe consistently."
            )
        return type(
            "DetectedDialect",
            (csv.Dialect,),
            {
                "delimiter": candidates[0],
                "quotechar": '"',
                "escapechar": None,
                "doublequote": True,
                "skipinitialspace": False,
                "lineterminator": "\r\n",
                "quoting": csv.QUOTE_MINIMAL,
                "strict": True,
            },
        )()
