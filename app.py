from flask import Flask, request, jsonify
import random
import os
import json
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

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
        data = request.get_json(force=True)

        room = data.get("room", "")
        sender = data.get("sender", "")
        msg = data.get("msg", "")

        if not msg:
            return jsonify({"reply": ""})

        if msg == "!테스트":
            return jsonify({"reply": "✅ 테스트 성공"})

        elif msg == "!주사위":
            return jsonify({"reply": f"🎲 {random.randint(1, 6)}"})

        elif msg == "!출석":
            today = datetime.utcnow().strftime("%Y-%m-%d")
            doc_id = f"{room}_{sender}_{today}"
            ref = db.collection("attendance").document(doc_id)
            doc = ref.get()

            if doc.exists:
                return jsonify({"reply": f"📌 {sender}님 오늘 이미 출석했어!"})
            else:
                ref.set({
                    "room": room,
                    "sender": sender,
                    "date": today,
                    "createdAt": firestore.SERVER_TIMESTAMP
                })
                return jsonify({"reply": f"✅ {sender}님 출석 완료!"})

        return jsonify({"reply": ""})

    except Exception as e:
        print("BOT ERROR:", str(e))
        return jsonify({"reply": "❌ 서버 내부 오류: " + str(e)}), 500
