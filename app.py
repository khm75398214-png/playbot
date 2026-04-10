from flask import Flask, request, jsonify
import random
import os
import json
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# Firebase 초기화
firebase_key = os.environ.get("FIREBASE_KEY")
if not firebase_key:
    raise ValueError("FIREBASE_KEY 환경변수가 없습니다.")

service_account = json.loads(firebase_key)
cred = credentials.Certificate(service_account)
firebase_admin.initialize_app(cred)
db = firestore.client()


@app.route("/", methods=["GET"])
def home():
    return "ATBOT SERVER ON"


@app.route("/bot", methods=["POST"])
def bot():
    try:
        data = request.get_json(silent=True)

        if not data:
            return jsonify({"reply": "❌ JSON 데이터가 없습니다."})

        room = data.get("room", "")
        sender = data.get("sender", "")
        msg = data.get("msg", "")

        if not msg:
            return jsonify({"reply": ""})

        reply = ""

        # !테스트
        if msg == "!테스트":
            reply = "✅ 놀이봇 정상 작동 중!"

        # !도움말
        elif msg == "!도움말":
            reply = (
                "🎮 놀이봇 명령어\n"
                "!테스트\n"
                "!주사위\n"
                "!동전\n"
                "!운세\n"
                "!가위바위보 가위/바위/보\n"
                "!랜덤숫자 1 100\n"
                "!오늘의음식\n"
                "!뽑기\n"
                "!출석"
            )

        # !주사위
        elif msg == "!주사위":
            dice = random.randint(1, 6)
            reply = f"🎲 주사위 결과: {dice}"

        # !동전
        elif msg == "!동전":
            result = random.choice(["앞면", "뒷면"])
            reply = f"🪙 동전 결과: {result}"

        # !운세
        elif msg == "!운세":
            fortunes = [
                "오늘은 운이 좋아!",
                "좋은 일이 생길 가능성이 커!",
                "무리하지 않으면 괜찮은 하루야.",
                "뜻밖의 연락이 올 수도 있어.",
                "작은 선택이 큰 차이를 만들 수 있어."
            ]
            reply = f"🔮 오늘의 운세: {random.choice(fortunes)}"

        # !가위바위보 가위
        elif msg.startswith("!가위바위보 "):
            user_pick = msg.replace("!가위바위보 ", "").strip()
            choices = ["가위", "바위", "보"]
            bot_pick = random.choice(choices)

            if user_pick not in choices:
                reply = "사용법: !가위바위보 가위/바위/보"
            else:
                if user_pick == bot_pick:
                    result = "비김"
                elif (
                    (user_pick == "가위" and bot_pick == "보") or
                    (user_pick == "바위" and bot_pick == "가위") or
                    (user_pick == "보" and bot_pick == "바위")
                ):
                    result = "너 승리!"
                else:
                    result = "봇 승리!"

                reply = f"✌ 너: {user_pick}\n🤖 봇: {bot_pick}\n📢 결과: {result}"

        # !랜덤숫자 1 100
        elif msg.startswith("!랜덤숫자 "):
            parts = msg.split()

            if len(parts) != 3:
                reply = "사용법: !랜덤숫자 1 100"
            else:
                try:
                    min_num = int(parts[1])
                    max_num = int(parts[2])

                    if min_num > max_num:
                        reply = "최솟값이 최댓값보다 클 수 없어."
                    else:
                        num = random.randint(min_num, max_num)
                        reply = f"🎯 {min_num}~{max_num} 사이 랜덤 숫자: {num}"
                except ValueError:
                    reply = "숫자를 올바르게 입력해줘."

        # !오늘의음식
        elif msg == "!오늘의음식":
            foods = [
                "치킨", "떡볶이", "피자", "햄버거",
                "라면", "돈까스", "김치찌개", "제육볶음"
            ]
            reply = f"🍽 오늘의 음식 추천: {random.choice(foods)}"

        # !뽑기
        elif msg == "!뽑기":
            items = ["꽝", "꽝", "소소한 행운", "간식 당첨", "대박 당첨"]
            reply = f"🎁 뽑기 결과: {random.choice(items)}"

        # !출석
        elif msg == "!출석":
            today = datetime.utcnow().strftime("%Y-%m-%d")
            doc_id = f"{room}_{sender}_{today}"
            ref = db.collection("attendance").document(doc_id)
            doc = ref.get()

            if doc.exists:
                reply = f"📌 {sender}님 오늘 이미 출석했어!"
            else:
                ref.set({
                    "room": room,
                    "sender": sender,
                    "date": today,
                    "createdAt": firestore.SERVER_TIMESTAMP
                })
                reply = f"✅ {sender}님 출석 완료!"

        return jsonify({"reply": reply})

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"reply": "❌ 서버 오류"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
