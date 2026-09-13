"""Quick tests for the parsing / vCard logic. Run with:  python test_converter.py"""

from converter import clean_phone, parse_contacts, build_vcf, convert_text_to_vcf

# A small sample that mirrors the real export, including the quirks:
#  - a header row
#  - the same contact repeated per source account (dedupe)
#  - the same name with two different numbers (keep both)
#  - messy numbers: trailing 'p', trailing ';', spaces, and a '+'
SAMPLE = "\n".join(
    [
        "\t\tname\tnumber\tconnected-via",
        "\t\tRam\t+919322363970\tcom.android.local",
        "\t\tRam\t+919322363970\tcom.google",
        "\t\tRam\t+919322363970\tcom.whatsapp",
        "\t\tSita\t8010716376\tcom.android.local",
        "\t\tSita\t8010716376\tcom.google",
        "\t\tRaju\t+918830341657\tcom.android.local",
        "\t\tRaju\t+918862093530\tcom.android.local",  # same name, 2nd number
        "\t\tAnna\t89996 71073\tcom.google",           # space inside number
        "\t\tGita\t7387381517;\tcom.google",           # trailing ;
        "\t\tVandana\t+919421414002p\tcom.google",      # trailing p
        "\t\tVaibhav\t+91 87660 66168\tcom.whatsapp",   # + and spaces
        "\t\t\t\tcom.google",                            # junk / no data
    ]
)


def test_clean_phone():
    assert clean_phone("+919322363970") == "+919322363970"
    assert clean_phone("8010716376") == "8010716376"
    assert clean_phone("89996 71073") == "8999671073"
    assert clean_phone("7387381517;") == "7387381517"
    assert clean_phone("+919421414002p") == "+919421414002"
    assert clean_phone("+91 87660 66168") == "+918766066168"
    assert clean_phone("number") == ""
    assert clean_phone("   ") == ""


def test_parse_dedupes_and_keeps_distinct_numbers():
    contacts = parse_contacts(SAMPLE)
    pairs = [(c.name, c.phone) for c in contacts]

    # Header and junk row dropped; per-source duplicates collapsed.
    assert ("Ram", "+919322363970") in pairs
    assert pairs.count(("Ram", "+919322363970")) == 1
    assert ("Sita", "8010716376") in pairs

    # Same name, two different numbers -> two entries.
    assert ("Raju", "+918830341657") in pairs
    assert ("Raju", "+918862093530") in pairs

    # Messy numbers cleaned.
    assert ("Anna", "8999671073") in pairs
    assert ("Gita", "7387381517") in pairs
    assert ("Vandana", "+919421414002") in pairs
    assert ("Vaibhav", "+918766066168") in pairs

    # No header, no empty rows.
    assert all(name != "name" for name, _ in pairs)
    assert len(pairs) == 8


def test_build_vcf_structure():
    contacts = parse_contacts(SAMPLE)
    vcf = build_vcf(contacts)
    assert vcf.count("BEGIN:VCARD") == len(contacts)
    assert vcf.count("END:VCARD") == len(contacts)
    assert "VERSION:3.0" in vcf
    assert "FN:Ram" in vcf
    assert "TEL;TYPE=CELL:+919322363970" in vcf


def test_convert_wrapper():
    vcf, count = convert_text_to_vcf(SAMPLE)
    assert count == 8
    assert vcf.count("BEGIN:VCARD") == 8


def test_unicode_names_preserved():
    text = "\t\tहीनुमत किदौ\t+919322363970\tcom.google"
    vcf, count = convert_text_to_vcf(text)
    assert count == 1
    assert "FN:हीनुमत किदौ" in vcf


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\nAll {passed} tests passed.")
