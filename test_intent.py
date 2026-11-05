"""Quick intent detection test"""
import intent_detector

tests = [
    ("give polymorphism code in java",    "code_request"),
    ("explain polymorphism",              "explain"),
    ("fix this sql query",                "debug"),
    ("build me a food delivery app",      "project_plan"),
    ("hi",                                "general"),
    ("what is machine learning",          "explain"),
    ("optimize this code",                "optimize"),
    ("python vs java",                    "compare"),
    ("interview questions for java",      "interview_prep"),
    ("design a scalable chat system",     "architecture"),
    ("hello jarvis",                      "general"),
    ("write a program to sort array in python", "code_request"),
    ("debug this error in my code",       "debug"),
    ("what time is it",                   "quick_answer"),
]

print("=" * 75)
print(f"  {'QUERY':45s}  {'GOT':15s}  {'EXPECTED':15s}  RESULT")
print("-" * 75)
passed = 0
for q, expected in tests:
    result = intent_detector.detect(q)
    ok = "PASS" if result.intent == expected else "FAIL"
    if ok == "PASS":
        passed += 1
    print(f"  {q:45s}  {result.intent:15s}  {expected:15s}  {ok}")
print("=" * 75)
print(f"  {passed}/{len(tests)} passed")
