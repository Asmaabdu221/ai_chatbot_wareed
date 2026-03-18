from app.services.runtime.text_normalizer import normalize_arabic  # temp

s = "".join(
    chr(x)
    for x in [
        0x0648,
        0x0634,
        0x20,
        0x0627,
        0x0644,
        0x062E,
        0x062F,
        0x0645,
        0x0627,
        0x062A,
        0x20,
        0x0627,
        0x0644,
        0x0644,
        0x064A,
    ]
)
print("repr", repr(s))
print("norm", repr(normalize_arabic(s)))
