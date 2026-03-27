from app.services.runtime.results_engine import interpret_result_query

tests = [
    "Vitamin D 10",
    "Vitamin D 50",
    "Calcitonin 5",
    "TSH 7.5",
    "Brucella 1:80",
    "نتيجتي فيتامين د 12",
    "فسر لي النتيجة"
]

for t in tests:
    print("INPUT:", t)
    try:
        result = interpret_result_query(t)
        print("OUTPUT:", result)
    except Exception as e:
        print("ERROR:", str(e))
    print("------------")
