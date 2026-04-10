from flask import Flask, request, jsonify
import random
import os
import json
from datetime import datetime, timezone, timedelta

import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ======================================
# Firebase 초기화
# ======================================
firebase_key = os.environ.get("FIREBASE_KEY")
if not firebase_key:
    raise ValueError("FIREBASE_KEY 환경변수가 없습니다.")

service_account = json.loads(firebase_key)
cred = credentials.Certificate(service_account)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ======================================
# 기본 설정
# ======================================
KST = timezone(timedelta(hours=9))

ADMIN_USERS = ["나", "헤헤", "가오니"]   # 관리자 닉네임
ALLOWED_ROOMS = []  # 비워두면 전체 방 허용, 제한하려면 ["테스트방", "AT클랜"] 이런 식

CHAT_EXP_MIN = 2
CHAT_EXP_MAX = 5
ATTENDANCE_EXP = 30
ATTENDANCE_POINTS = 100

# 너무 짧은 메시지는 경험치 지급 안 하도록
MIN_MSG_LENGTH_FOR_EXP = 2

# 같은 사람이 너무 짧은 시간 안에 연속으로 경험치 먹는 거 방지
CHAT_EXP_COOLDOWN_SEC = 20


# ======================================
# 공통 함수
# ======================================
def now_kst():
    return datetime.now(KST)


def today_str():
    return now_kst().strftime("%Y-%m-%d")


def is_admin(sender):
    return sender in ADMIN_USERS


def user_doc_id(room, sender):
    return f"{room}__{sender}"


def get_user_ref(room, sender):
    return db.collection("users").document(user_doc_id(room, sender))


def exp_needed(level):
    # 레벨업 필요 경험치
    # 취향대로 조절 가능
    return 50 + (level - 1) * 20


def get_level_start_exp(level):
    total = 0
    for lv in range(1, level):
        total += exp_needed(lv)
    return total


def sync_level_from_exp(user_data):
    total_exp = int(user_data.get("total_exp", 0))
    level = 1
    remain = total_exp

    while remain >= exp_needed(level):
        remain -= exp_needed(level)
        level += 1

    user_data["level"] = level
    user_data["exp"] = remain
    return user_data


def ensure_user(room, sender):
    ref = get_user_ref(room, sender)
    doc = ref.get()

    if not doc.exists:
        data = {
            "room": room,
            "sender": sender,
            "level": 1,
            "exp": 0,
            "total_exp": 0,
            "points": 0,
            "messages": 0,
            "last_attendance": "",
            "last_chat_exp_at": 0,
            "created_at": firestore.SERVER_TIMESTAMP
        }
        ref.set(data)
        return data, ref

    return doc.to_dict(), ref


def add_exp(room, sender, amount):
    user_data, ref = ensure_user(room, sender)

    old_level = int(user_data.get("level", 1))
    new_total_exp = int(user_data.get("total_exp", 0)) + int(amount)

    user_data["total_exp"] = new_total_exp
    user_data = sync_level_from_exp(user_data)

    ref.update({
        "level": user_data["level"],
        "exp": user_data["exp"],
        "total_exp": user_data["total_exp"]
    })

    leveled_up = user_data["level"] > old_level
    return user_data, leveled_up, old_level


def add_points(room, sender, amount):
    user_data, ref = ensure_user(room, sender)
    new_points = int(user_data.get("points", 0)) + int(amount)

    ref.update({
        "points": new_points
    })

    user_data["points"] = new_points
    return user_data


def can_gain_chat_exp(user_data):
    now_ts = int(now_kst().timestamp())
    last_ts = int(user_data.get("last_chat_exp_at", 0))
    return (now_ts - last_ts) >= CHAT_EXP_COOLDOWN_SEC


def process_chat_exp(room, sender, msg):
    # 명령어는 여기서 처리 안 함
    if msg.startswith("!"):
        return None

    if len(msg.strip()) < MIN_MSG_LENGTH_FOR_EXP:
        return None

    user_data, ref = ensure_user(room, sender)

    if not can_gain_chat_exp(user_data):
        return None

    gained_exp = random.randint(CHAT_EXP_MIN, CHAT_EXP_MAX)

    old_level = int(user_data.get("level", 1))
    new_total_exp = int(user_data.get("total_exp", 0)) + gained_exp
    new_messages = int(user_data.get("messages", 0)) + 1
    now_ts = int(now_kst().timestamp())

    user_data["total_exp"] = new_total_exp
    user_data["messages"] = new_messages
    user_data["last_chat_exp_at"] = now_ts
    user_data = sync_level_from_exp(user_data)

    ref.update({
        "level": user_data["level"],
        "exp": user_data["exp"],
        "total_exp": user_data["total_exp"],
        "messages": new_messages,
        "last_chat_exp_at": now_ts
    })

    if user_data["level"] > old_level:
        return (
            f"🎉 {sender}님 레벨업!\n"
            f"Lv.{old_level} → Lv.{user_data['level']}\n"
            f"현재 경험치: {user_data['exp']} / {exp_needed(user_data['level'])}"
        )

    return None


def allowed_room(room):
    if not ALLOWED_ROOMS:
        return True
    return room in ALLOWED_ROOMS


# ======================================
# 라우팅
# ======================================
@app.route("/", methods=["GET"])
def home():
    return "ATBOT SERVER ON"


@app.route("/bot", methods=["POST"])
def bot():
    try:
        data = request.get_json(force=True)

        room = data.get("room", "").strip()
        sender = data.get("sender", "").strip()
        msg = data.get("msg", "").strip()

        if not room or not sender or not msg:
            return jsonify({"reply": ""})

        if not allowed_room(room):
            return jsonify({"reply": ""})

        # 유저 기본 생성
        ensure_user(room, sender)

        reply = ""

        # ======================================
        # 일반 채팅 경험치
        # ======================================
        chat_exp_reply = process_chat_exp(room, sender, msg)
        if chat_exp_reply:
            return jsonify({"reply": chat_exp_reply})

        # ======================================
        # 명령어 처리
        # ======================================

        if msg == "!테스트":
            reply = "✅ 봇 정상 작동 중!"

        elif msg == "!도움말":
            reply = (
                "🎮 놀이봇 명령어\n\n"
                "📌 기본\n"
                "!테스트\n"
                "!도움말\n"
                "!레벨\n"
                "!포인트\n"
                "!출석\n"
                "!랭킹\n"
                "!송금 닉네임 금액\n\n"
                "🎲 놀이\n"
                "!주사위\n"
                "!동전\n"
                "!운세\n"
                "!가위바위보 가위/바위/보\n"
                "!랜덤숫자 1 100\n"
                "!오늘의음식\n"
                "!뽑기\n\n"
                "👑 관리자\n"
                "!관리자목록\n"
                "!레벨추가 닉네임 수치\n"
                "!경험치추가 닉네임 수치\n"
                "!포인트추가 닉네임 수치"
            )

        elif msg == "!관리자목록":
            reply = "👑 관리자 목록\n" + "\n".join(ADMIN_USERS)

        # --------------------------------------
        # 유저 정보
        # --------------------------------------
        elif msg == "!레벨":
            user_data, _ = ensure_user(room, sender)
            level = int(user_data.get("level", 1))
            exp = int(user_data.get("exp", 0))
            total_exp = int(user_data.get("total_exp", 0))
            messages = int(user_data.get("messages", 0))

            reply = (
                f"📊 {sender}님의 정보\n"
                f"레벨: Lv.{level}\n"
                f"경험치: {exp} / {exp_needed(level)}\n"
                f"누적 경험치: {total_exp}\n"
                f"채팅 수: {messages}"
            )

        elif msg == "!포인트":
            user_data, _ = ensure_user(room, sender)
            points = int(user_data.get("points", 0))
            reply = f"💰 {sender}님의 포인트: {points}"

        elif msg == "!출석":
            user_data, ref = ensure_user(room, sender)
            today = today_str()
            last_attendance = user_data.get("last_attendance", "")

            if last_attendance == today:
                reply = f"📌 {sender}님 오늘 이미 출석했어!"
            else:
                new_points = int(user_data.get("points", 0)) + ATTENDANCE_POINTS
                new_total_exp = int(user_data.get("total_exp", 0)) + ATTENDANCE_EXP
                old_level = int(user_data.get("level", 1))

                user_data["points"] = new_points
                user_data["total_exp"] = new_total_exp
                user_data["last_attendance"] = today
                user_data = sync_level_from_exp(user_data)

                ref.update({
                    "points": new_points,
                    "total_exp": user_data["total_exp"],
                    "level": user_data["level"],
                    "exp": user_data["exp"],
                    "last_attendance": today
                })

                reply = (
                    f"✅ {sender}님 출석 완료!\n"
                    f"+{ATTENDANCE_POINTS} 포인트\n"
                    f"+{ATTENDANCE_EXP} 경험치"
                )

                if user_data["level"] > old_level:
                    reply += f"\n🎉 레벨업! Lv.{old_level} → Lv.{user_data['level']}"

        elif msg == "!랭킹":
            docs = db.collection("users").where("room", "==", room).stream()

            users = []
            for doc in docs:
                d = doc.to_dict()
                users.append({
                    "sender": d.get("sender", "알수없음"),
                    "level": int(d.get("level", 1)),
                    "total_exp": int(d.get("total_exp", 0)),
                    "points": int(d.get("points", 0))
                })

            users.sort(key=lambda x: (x["level"], x["total_exp"], x["points"]), reverse=True)

            if not users:
                reply = "랭킹 데이터가 없어."
            else:
                lines = ["🏆 랭킹 TOP 10"]
                for i, user in enumerate(users[:10], start=1):
                    lines.append(
                        f"{i}. {user['sender']} | Lv.{user['level']} | EXP {user['total_exp']} | 💰 {user['points']}"
                    )
                reply = "\n".join(lines)

        elif msg.startswith("!송금 "):
            parts = msg.split()

            if len(parts) != 3:
                reply = "사용법: !송금 닉네임 금액"
            else:
                target_name = parts[1]

                try:
                    amount = int(parts[2])

                    if amount <= 0:
                        reply = "1 이상의 숫자만 가능해."
                    elif target_name == sender:
                        reply = "자기 자신에게는 송금할 수 없어."
                    else:
                        my_data, my_ref = ensure_user(room, sender)
                        target_data, target_ref = ensure_user(room, target_name)

                        my_points = int(my_data.get("points", 0))
                        if my_points < amount:
                            reply = "포인트가 부족해."
                        else:
                            target_points = int(target_data.get("points", 0)) + amount
                            my_new_points = my_points - amount

                            my_ref.update({"points": my_new_points})
                            target_ref.update({"points": target_points})

                            reply = (
                                f"💸 송금 완료!\n"
                                f"{sender} → {target_name}\n"
                                f"금액: {amount}\n"
                                f"내 포인트: {my_new_points}"
                            )
                except ValueError:
                    reply = "숫자를 올바르게 입력해줘."

        # --------------------------------------
        # 놀이 명령어
        # --------------------------------------
        elif msg == "!주사위":
            dice = random.randint(1, 6)
            reply = f"🎲 주사위 결과: {dice}"

        elif msg == "!동전":
            result = random.choice(["앞면", "뒷면"])
            reply = f"🪙 동전 결과: {result}"

        elif msg == "!운세":
            fortunes = [
                "오늘은 운이 좋아!",
                "좋은 일이 생길 가능성이 커!",
                "무리하지 않으면 괜찮은 하루야.",
                "뜻밖의 연락이 올 수도 있어.",
                "작은 선택이 큰 차이를 만들 수 있어.",
                "오늘은 너무 급하게 움직이지 않는 게 좋아.",
                "작은 행운이 따라오는 날이야."
            ]
            reply = f"🔮 오늘의 운세: {random.choice(fortunes)}"

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

                reply = (
                    f"✌ 너: {user_pick}\n"
                    f"🤖 봇: {bot_pick}\n"
                    f"📢 결과: {result}"
                )

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

        elif msg == "!오늘의음식":
            foods = [
                "치킨", "떡볶이", "피자", "햄버거",
                "라면", "돈까스", "김치찌개", "제육볶음",
                "국밥", "마라탕", "삼겹살", "초밥"
            ]
            reply = f"🍽 오늘의 음식 추천: {random.choice(foods)}"

        elif msg == "!뽑기":
            items = ["꽝", "꽝", "소소한 행운", "간식 당첨", "대박 당첨", "완전 럭키"]
            reply = f"🎁 뽑기 결과: {random.choice(items)}"

        # --------------------------------------
        # 관리자 명령어
        # --------------------------------------
        elif msg.startswith("!레벨추가 "):
            if not is_admin(sender):
                reply = "⛔ 관리자만 사용할 수 있어."
            else:
                parts = msg.split()
                if len(parts) != 3:
                    reply = "사용법: !레벨추가 닉네임 수치"
                else:
                    target_name = parts[1]
                    try:
                        add_level_num = int(parts[2])
                        if add_level_num <= 0:
                            reply = "1 이상의 숫자만 가능해."
                        else:
                            target_data, target_ref = ensure_user(room, target_name)
                            current_level = int(target_data.get("level", 1))
                            new_level = current_level + add_level_num
                            total_exp = get_level_start_exp(new_level)

                            target_ref.update({
                                "level": new_level,
                                "exp": 0,
                                "total_exp": total_exp
                            })

                            reply = (
                                f"🛠 {target_name}님 레벨을 {add_level_num} 올렸어!\n"
                                f"현재 레벨: Lv.{new_level}"
                            )
                    except ValueError:
                        reply = "숫자를 올바르게 입력해줘."

        elif msg.startswith("!경험치추가 "):
            if not is_admin(sender):
                reply = "⛔ 관리자만 사용할 수 있어."
            else:
                parts = msg.split()
                if len(parts) != 3:
                    reply = "사용법: !경험치추가 닉네임 수치"
                else:
                    target_name = parts[1]
                    try:
                        add_exp_num = int(parts[2])
                        if add_exp_num <= 0:
                            reply = "1 이상의 숫자만 가능해."
                        else:
                            target_data, target_ref = ensure_user(room, target_name)

                            target_data["total_exp"] = int(target_data.get("total_exp", 0)) + add_exp_num
                            target_data = sync_level_from_exp(target_data)

                            target_ref.update({
                                "level": target_data["level"],
                                "exp": target_data["exp"],
                                "total_exp": target_data["total_exp"]
                            })

                            reply = (
                                f"✨ {target_name}님에게 경험치 {add_exp_num} 지급!\n"
                                f"현재 레벨: Lv.{target_data['level']}\n"
                                f"현재 경험치: {target_data['exp']} / {exp_needed(target_data['level'])}"
                            )
                    except ValueError:
                        reply = "숫자를 올바르게 입력해줘."

        elif msg.startswith("!포인트추가 "):
            if not is_admin(sender):
                reply = "⛔ 관리자만 사용할 수 있어."
            else:
                parts = msg.split()
                if len(parts) != 3:
                    reply = "사용법: !포인트추가 닉네임 수치"
                else:
                    target_name = parts[1]
                    try:
                        add_points_num = int(parts[2])
                        if add_points_num <= 0:
                            reply = "1 이상의 숫자만 가능해."
                        else:
                            target_data, target_ref = ensure_user(room, target_name)
                            new_points = int(target_data.get("points", 0)) + add_points_num

                            target_ref.update({
                                "points": new_points
                            })

                            reply = (
                                f"💰 {target_name}님에게 {add_points_num} 포인트 지급!\n"
                                f"현재 포인트: {new_points}"
                            )
                    except ValueError:
                        reply = "숫자를 올바르게 입력해줘."

        return jsonify({"reply": reply})

    except Exception as e:
        print("BOT ERROR:", str(e))
        return jsonify({"reply": "❌ 서버 내부 오류: " + str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
