def process(form_data):
    # 症状からAIが最大10種類の漢方を提案（仮）
    symptoms = form_data.get("symptoms", "")
    top10 = ["漢方A", "漢方B", "漢方C"]
    top3 = top10[:3]
    return {
        "patient": form_data,
        "top10": top10,
        "top3": top3,
        "advice": "日常生活や薬膳アドバイス（仮）"
    }
