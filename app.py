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

ADMIN_USERS = ["가오니", "가오니2"]
ALLOWED_ROOMS = []

CHAT_EXP_MIN = 2
CHAT_EXP_MAX = 5
ATTENDANCE_EXP = 30
ATTENDANCE_POINTS = 100
MIN_MSG_LENGTH_FOR_EXP = 2
CHAT_EXP_COOLDOWN_SEC = 20

HUNT_COOLDOWN_SEC = 30
FISH_COOLDOWN_SEC = 25
MINE_COOLDOWN_SEC = 25

ITEM_DROP_TABLE = [
    {"name": "낡은 검", "type": "weapon", "grade": "common", "chance": 30},
    {"name": "낡은 갑옷", "type": "armor", "grade": "common", "chance": 30},
    {"name": "고블린 단검", "type": "weapon", "grade": "rare", "chance": 18},
    {"name": "가죽 갑옷", "type": "armor", "grade": "rare", "chance": 12},
    {"name": "강철 검", "type": "weapon", "grade": "epic", "chance": 6},
    {"name": "강철 갑옷", "type": "armor", "grade": "epic", "chance": 3},
    {"name": "용사의 검", "type": "weapon", "grade": "legend", "chance": 1},
]

FISH_TABLE = [
    {"name": "작은 물고기", "type": "material", "grade": "common", "chance": 40, "sell_price": 20},
    {"name": "붕어", "type": "material", "grade": "common", "chance": 25, "sell_price": 35},
    {"name": "잉어", "type": "material", "grade": "rare", "chance": 18, "sell_price": 60},
    {"name": "황금 물고기", "type": "material", "grade": "epic", "chance": 10, "sell_price": 150},
    {"name": "전설의 물고기", "type": "material", "grade": "legend", "chance": 7, "sell_price": 350},
]

MINE_TABLE = [
    {"name": "돌", "type": "material", "grade": "common", "chance": 35, "sell_price": 15},
    {"name": "석탄", "type": "material", "grade": "common", "chance": 25, "sell_price": 30},
    {"name": "철광석", "type": "material", "grade": "rare", "chance": 18, "sell_price": 70},
    {"name": "금광석", "type": "material", "grade": "epic", "chance": 12, "sell_price": 160},
    {"name": "다이아 원석", "type": "material", "grade": "legend", "chance": 10, "sell_price": 400},
]

SHOP_ITEMS = {
    "회복약": {"price": 120, "type": "consumable", "desc": "나중에 확장용 아이템"},
    "강화서": {"price": 300, "type": "consumable", "desc": "강화용 특수 아이템"},
    "낚싯대": {"price": 500, "type": "tool", "desc": "낚시 성공 기분상 상승"},
    "곡괭이": {"price": 500, "type": "tool", "desc": "광산 채굴 기분상 상승"},
}

GRADE_BONUS = {
    "common": 1,
    "rare": 3,
    "epic": 6,
    "legend": 10
}

GRADE_KOR = {
    "common": "일반",
    "rare": "레어",
    "epic": "에픽",
    "legend": "레전드"
}

SELL_PRICE_BY_GRADE = {
    "common": 40,
    "rare": 90,
    "epic": 180,
    "legend": 400
}


# ======================================
# 공통 함수
# ======================================
def now_kst():
    return datetime.now(KST)


def today_str():
    return now_kst().strftime("%Y-%m-%d")


def is_admin(sender):
    return sender in ADMIN_USERS


def allowed_room(room):
    if not ALLOWED_ROOMS:
        return True
    return room in ALLOWED_ROOMS


def user_doc_id(room, sender):
    return f"{room}__{sender}"


def get_user_ref(room, sender):
    return db.collection("users").document(user_doc_id(room, sender))


def exp_needed(level):
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


def make_empty_equipment():
    return {
        "weapon": None,
        "armor": None
    }


def make_default_user(room, sender):
    return {
        "room": room,
        "sender": sender,
        "level": 1,
        "exp": 0,
        "total_exp": 0,
        "points": 0,
        "messages": 0,
        "last_attendance": "",
        "last_chat_exp_at": 0,
        "last_hunt_at": 0,
        "last_fish_at": 0,
        "last_mine_at": 0,
        "inventory": [],
        "equipment": make_empty_equipment(),
        "created_at": firestore.SERVER_TIMESTAMP
    }


def ensure_user(room, sender):
    ref = get_user_ref(room, sender)
    doc = ref.get()

    if not doc.exists:
        data = make_default_user(room, sender)
        ref.set(data)
        return data, ref

    data = doc.to_dict()

    changed = False
    if "inventory" not in data:
        data["inventory"] = []
        changed = True
    if "equipment" not in data:
        data["equipment"] = make_empty_equipment()
        changed = True
    for key in ["last_hunt_at", "last_fish_at", "last_mine_at"]:
        if key not in data:
            data[key] = 0
            changed = True

    if changed:
        ref.set(data, merge=True)

    return data, ref


def add_points(room, sender, amount):
    user_data, ref = ensure_user(room, sender)
    new_points = int(user_data.get("points", 0)) + int(amount)
    ref.update({"points": new_points})
    user_data["points"] = new_points
    return user_data


def can_gain_chat_exp(user_data):
    now_ts = int(now_kst().timestamp())
    last_ts = int(user_data.get("last_chat_exp_at", 0))
    return (now_ts - last_ts) >= CHAT_EXP_COOLDOWN_SEC


def process_chat_exp(room, sender, msg):
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


# ======================================
# 아이템 / 장비
# ======================================
def make_item(name, item_type, grade, sell_price=None):
    item = {
        "id": f"{int(now_kst().timestamp() * 1000)}_{random.randint(1000, 9999)}",
        "name": name,
        "type": item_type,
        "grade": grade,
        "enhance": 0
    }
    if sell_price is not None:
        item["sell_price"] = sell_price
    return item


def get_item_power(item):
    if not item:
        return 0
    if item.get("type") not in ["weapon", "armor"]:
        return 0
    base = GRADE_BONUS.get(item.get("grade", "common"), 1)
    enhance = int(item.get("enhance", 0))
    return base + enhance


def get_total_combat_power(user_data):
    equipment = user_data.get("equipment", {})
    weapon = equipment.get("weapon")
    armor = equipment.get("armor")
    return get_item_power(weapon) + get_item_power(armor) + int(user_data.get("level", 1))


def add_item_to_inventory(user_data, ref, item):
    inventory = user_data.get("inventory", [])
    inventory.append(item)
    user_data["inventory"] = inventory
    ref.update({"inventory": inventory})


def remove_item_by_id(user_data, ref, item_id):
    inventory = user_data.get("inventory", [])
    new_inventory = [item for item in inventory if item.get("id") != item_id]
    user_data["inventory"] = new_inventory
    ref.update({"inventory": new_inventory})


def format_item(item):
    if not item:
        return "없음"
    extra = ""
    if item.get("type") in ["weapon", "armor"]:
        extra = f" +{item.get('enhance', 0)}"
    return f"{item['name']} [{GRADE_KOR.get(item['grade'], item['grade'])}]{extra}"


def pick_from_weighted_table(table):
    roll = random.randint(1, 100)
    current = 0
    for item in table:
        current += item["chance"]
        if roll <= current:
            return item
    return table[-1]


def pick_random_drop():
    picked = pick_from_weighted_table(ITEM_DROP_TABLE)
    return make_item(picked["name"], picked["type"], picked["grade"])


def pick_fish_drop():
    picked = pick_from_weighted_table(FISH_TABLE)
    return make_item(
        picked["name"],
        picked["type"],
        picked["grade"],
        sell_price=picked["sell_price"]
    )


def pick_mine_drop():
    picked = pick_from_weighted_table(MINE_TABLE)
    return make_item(
        picked["name"],
        picked["type"],
        picked["grade"],
        sell_price=picked["sell_price"]
    )


def get_enhance_cost(item):
    if not item:
        return None
    return 100 + (int(item.get("enhance", 0)) * 80)


def enhance_success_rate(item):
    if not item:
        return 0
    lv = int(item.get("enhance", 0))
    if lv <= 2:
        return 90
    elif lv <= 4:
        return 70
    elif lv <= 6:
        return 50
    elif lv <= 8:
        return 35
    return 20


def try_enhance_item(item):
    current = int(item.get("enhance", 0))
    success_rate = enhance_success_rate(item)
    roll = random.randint(1, 100)

    if roll <= success_rate:
        item["enhance"] = current + 1
        return "success"

    if current >= 7:
        destroy_roll = random.randint(1, 100)
        if destroy_roll <= 25:
            return "destroy"

    return "fail"


def auto_equip_dropped_item(user_data, ref, dropped_item):
    equipment = user_data.get("equipment", make_empty_equipment())
    slot = dropped_item["type"]
    equipped = equipment.get(slot)

    if equipped is None:
        equipment[slot] = dropped_item
        user_data["equipment"] = equipment
        ref.update({"equipment": equipment})
        return f"🧤 자동 장착됨: {format_item(dropped_item)}"

    if get_item_power(dropped_item) > get_item_power(equipped):
        old_item = equipped
        inventory = user_data.get("inventory", [])
        inventory.append(old_item)
        equipment[slot] = dropped_item

        user_data["inventory"] = inventory
        user_data["equipment"] = equipment
        ref.update({
            "inventory": inventory,
            "equipment": equipment
        })
        return f"⚔ 더 좋은 장비라 자동 장착!\n새 장비: {format_item(dropped_item)}\n기존 장비는 인벤토리로 이동"

    add_item_to_inventory(user_data, ref, dropped_item)
    return f"🎒 인벤토리에 저장됨: {format_item(dropped_item)}"


def get_sell_price(item):
    if "sell_price" in item:
        return int(item["sell_price"])
    return SELL_PRICE_BY_GRADE.get(item.get("grade", "common"), 20) + (int(item.get("enhance", 0)) * 20)


def equip_item_by_index(user_data, ref, idx):
    inventory = user_data.get("inventory", [])
    if idx < 0 or idx >= len(inventory):
        return False, "없는 인벤토리 번호야."

    item = inventory[idx]
    if item.get("type") not in ["weapon", "armor"]:
        return False, "그 아이템은 장착할 수 없어."

    slot = item["type"]
    equipment = user_data.get("equipment", make_empty_equipment())
    current_equipped = equipment.get(slot)

    new_inventory = inventory[:]
    new_inventory.pop(idx)

    if current_equipped is not None:
        new_inventory.append(current_equipped)

    equipment[slot] = item

    user_data["inventory"] = new_inventory
    user_data["equipment"] = equipment

    ref.update({
        "inventory": new_inventory,
        "equipment": equipment
    })

    return True, f"🧤 장착 완료: {format_item(item)}"


def unequip_slot(user_data, ref, slot_name):
    equipment = user_data.get("equipment", make_empty_equipment())
    item = equipment.get(slot_name)
    if item is None:
        return False, "해제할 장비가 없어."

    inventory = user_data.get("inventory", [])
    inventory.append(item)
    equipment[slot_name] = None

    user_data["inventory"] = inventory
    user_data["equipment"] = equipment

    ref.update({
        "inventory": inventory,
        "equipment": equipment
    })

    return True, f"📦 장착 해제: {format_item(item)}"


def use_activity_cooldown(user_data, ref, key, cooldown):
    now_ts = int(now_kst().timestamp())
    last_ts = int(user_data.get(key, 0))
    if now_ts - last_ts < cooldown:
        remain = cooldown - (now_ts - last_ts)
        return False, remain
    ref.update({key: now_ts})
    return True, 0


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

        ensure_user(room, sender)

        reply = ""

        chat_exp_reply = process_chat_exp(room, sender, msg)
        if chat_exp_reply:
            return jsonify({"reply": chat_exp_reply})

        if msg == "!테스트":
            reply = "✅ 봇 정상 작동 중!"

        elif msg == "!도움말":
            reply = (
                "🎮 놀이봇 명령어\n\n"
                "📌 기본\n"
                "!테스트\n!도움말\n!레벨\n!포인트\n!출석\n!랭킹\n!송금 닉네임 금액\n\n"
                "⚔ RPG\n"
                "!사냥\n!인벤토리\n!장비\n!장착 번호\n!장착해제 무기/방어구\n!강화 무기\n!강화 방어구\n\n"
                "🎣 채집\n"
                "!낚시\n!광산\n\n"
                "🛒 경제\n"
                "!상점\n!구매 아이템명\n!판매 번호\n!판매 전부\n\n"
                "🎲 놀이\n"
                "!주사위\n!동전\n!운세\n!가위바위보 가위/바위/보\n!랜덤숫자 1 100\n!오늘의음식\n!뽑기\n\n"
                "👑 관리자\n"
                "!관리자목록\n!레벨추가 닉네임 수치\n!경험치추가 닉네임 수치\n!포인트추가 닉네임 수치"
            )

        elif msg == "!관리자목록":
            reply = "👑 관리자 목록\n" + "\n".join(ADMIN_USERS)

        elif msg == "!레벨":
            user_data, _ = ensure_user(room, sender)
            level = int(user_data.get("level", 1))
            exp = int(user_data.get("exp", 0))
            total_exp = int(user_data.get("total_exp", 0))
            messages = int(user_data.get("messages", 0))
            power = get_total_combat_power(user_data)

            reply = (
                f"📊 {sender}님의 정보\n"
                f"레벨: Lv.{level}\n"
                f"경험치: {exp} / {exp_needed(level)}\n"
                f"누적 경험치: {total_exp}\n"
                f"채팅 수: {messages}\n"
                f"전투력: {power}"
            )

        elif msg == "!포인트":
            user_data, _ = ensure_user(room, sender)
            reply = f"💰 {sender}님의 포인트: {int(user_data.get('points', 0))}"

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

                reply = f"✅ {sender}님 출석 완료!\n+{ATTENDANCE_POINTS} 포인트\n+{ATTENDANCE_EXP} 경험치"
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
                    "points": int(d.get("points", 0)),
                    "power": get_total_combat_power(d)
                })

            users.sort(key=lambda x: (x["level"], x["total_exp"], x["power"], x["points"]), reverse=True)

            if not users:
                reply = "랭킹 데이터가 없어."
            else:
                lines = ["🏆 랭킹 TOP 10"]
                for i, user in enumerate(users[:10], start=1):
                    lines.append(f"{i}. {user['sender']} | Lv.{user['level']} | 전투력 {user['power']} | 💰 {user['points']}")
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
                            my_new_points = my_points - amount
                            target_new_points = int(target_data.get("points", 0)) + amount
                            my_ref.update({"points": my_new_points})
                            target_ref.update({"points": target_new_points})
                            reply = f"💸 송금 완료!\n{sender} → {target_name}\n금액: {amount}\n내 포인트: {my_new_points}"
                except ValueError:
                    reply = "숫자를 올바르게 입력해줘."

        # =========================
        # RPG / 장비
        # =========================
        elif msg == "!인벤토리":
            user_data, _ = ensure_user(room, sender)
            inventory = user_data.get("inventory", [])

            if not inventory:
                reply = "🎒 인벤토리가 비어 있어."
            else:
                lines = ["🎒 인벤토리"]
                for i, item in enumerate(inventory[:30], start=1):
                    lines.append(f"{i}. {format_item(item)} | 판매가 {get_sell_price(item)}")
                if len(inventory) > 30:
                    lines.append(f"... 외 {len(inventory) - 30}개")
                reply = "\n".join(lines)

        elif msg == "!장비":
            user_data, _ = ensure_user(room, sender)
            equipment = user_data.get("equipment", make_empty_equipment())
            weapon = equipment.get("weapon")
            armor = equipment.get("armor")
            power = get_total_combat_power(user_data)

            reply = (
                f"🛡 {sender}님의 장비\n"
                f"무기: {format_item(weapon)}\n"
                f"방어구: {format_item(armor)}\n"
                f"전투력: {power}"
            )

        elif msg.startswith("!장착 "):
            user_data, ref = ensure_user(room, sender)
            parts = msg.split()
            if len(parts) != 2:
                reply = "사용법: !장착 번호"
            else:
                try:
                    idx = int(parts[1]) - 1
                    ok, message = equip_item_by_index(user_data, ref, idx)
                    reply = message
                except ValueError:
                    reply = "번호를 올바르게 입력해줘."

        elif msg.startswith("!장착해제 "):
            user_data, ref = ensure_user(room, sender)
            slot_word = msg.replace("!장착해제 ", "").strip()

            if slot_word == "무기":
                ok, message = unequip_slot(user_data, ref, "weapon")
                reply = message
            elif slot_word == "방어구":
                ok, message = unequip_slot(user_data, ref, "armor")
                reply = message
            else:
                reply = "사용법: !장착해제 무기/방어구"

        elif msg == "!사냥":
            user_data, ref = ensure_user(room, sender)
            ok, remain = use_activity_cooldown(user_data, ref, "last_hunt_at", HUNT_COOLDOWN_SEC)
            if not ok:
                reply = f"⏳ 사냥은 조금 쉬었다가 해줘. {remain}초 남음"
            else:
                monsters = ["슬라임", "고블린", "늑대", "오크", "해골병사"]
                monster = random.choice(monsters)

                power = get_total_combat_power(user_data)
                win_rate = min(90, 50 + power * 3)
                roll = random.randint(1, 100)

                if roll <= win_rate:
                    gained_exp = random.randint(15, 35)
                    gained_points = random.randint(30, 80)

                    old_level = int(user_data.get("level", 1))
                    user_data["total_exp"] = int(user_data.get("total_exp", 0)) + gained_exp
                    user_data["points"] = int(user_data.get("points", 0)) + gained_points
                    user_data = sync_level_from_exp(user_data)

                    ref.update({
                        "total_exp": user_data["total_exp"],
                        "exp": user_data["exp"],
                        "level": user_data["level"],
                        "points": user_data["points"]
                    })

                    drop_msg = ""
                    if random.randint(1, 100) <= 55:
                        dropped_item = pick_random_drop()
                        drop_msg = "\n" + auto_equip_dropped_item(user_data, ref, dropped_item)

                    reply = f"⚔ {monster} 처치 성공!\n+{gained_exp} EXP\n+{gained_points} 포인트"
                    if user_data["level"] > old_level:
                        reply += f"\n🎉 레벨업! Lv.{old_level} → Lv.{user_data['level']}"
                    reply += drop_msg if drop_msg else "\n📦 아이템 드랍 없음"
                else:
                    lost_points = min(int(user_data.get("points", 0)), random.randint(5, 20))
                    new_points = int(user_data.get("points", 0)) - lost_points
                    ref.update({"points": new_points})
                    reply = f"💥 {monster}에게 패배했어...\n포인트 {lost_points} 잃음\n현재 포인트: {new_points}"

        elif msg == "!강화 무기":
            user_data, ref = ensure_user(room, sender)
            equipment = user_data.get("equipment", make_empty_equipment())
            weapon = equipment.get("weapon")

            if not weapon:
                reply = "⚠ 강화할 무기가 없어."
            else:
                cost = get_enhance_cost(weapon)
                points = int(user_data.get("points", 0))

                if points < cost:
                    reply = f"💰 포인트가 부족해. 필요 포인트: {cost}"
                else:
                    result = try_enhance_item(weapon)
                    new_points = points - cost

                    if result == "success":
                        equipment["weapon"] = weapon
                        ref.update({"points": new_points, "equipment": equipment})
                        reply = f"✨ 강화 성공!\n{format_item(weapon)}\n사용 포인트: {cost}"
                    elif result == "fail":
                        ref.update({"points": new_points})
                        reply = f"❌ 강화 실패...\n장비는 유지됐어.\n사용 포인트: {cost}"
                    else:
                        equipment["weapon"] = None
                        ref.update({"points": new_points, "equipment": equipment})
                        reply = f"💥 강화 대실패...\n무기가 파괴됐어.\n사용 포인트: {cost}"

        elif msg == "!강화 방어구":
            user_data, ref = ensure_user(room, sender)
            equipment = user_data.get("equipment", make_empty_equipment())
            armor = equipment.get("armor")

            if not armor:
                reply = "⚠ 강화할 방어구가 없어."
            else:
                cost = get_enhance_cost(armor)
                points = int(user_data.get("points", 0))

                if points < cost:
                    reply = f"💰 포인트가 부족해. 필요 포인트: {cost}"
                else:
                    result = try_enhance_item(armor)
                    new_points = points - cost

                    if result == "success":
                        equipment["armor"] = armor
                        ref.update({"points": new_points, "equipment": equipment})
                        reply = f"✨ 강화 성공!\n{format_item(armor)}\n사용 포인트: {cost}"
                    elif result == "fail":
                        ref.update({"points": new_points})
                        reply = f"❌ 강화 실패...\n장비는 유지됐어.\n사용 포인트: {cost}"
                    else:
                        equipment["armor"] = None
                        ref.update({"points": new_points, "equipment": equipment})
                        reply = f"💥 강화 대실패...\n방어구가 파괴됐어.\n사용 포인트: {cost}"

        # =========================
        # 채집
        # =========================
        elif msg == "!낚시":
            user_data, ref = ensure_user(room, sender)
            ok, remain = use_activity_cooldown(user_data, ref, "last_fish_at", FISH_COOLDOWN_SEC)

            if not ok:
                reply = f"⏳ 낚시는 조금 쉬었다가 해줘. {remain}초 남음"
            else:
                item = pick_fish_drop()
                gained_points = random.randint(10, 30)
                gained_exp = random.randint(8, 20)

                user_data["points"] = int(user_data.get("points", 0)) + gained_points
                user_data["total_exp"] = int(user_data.get("total_exp", 0)) + gained_exp
                old_level = int(user_data.get("level", 1))
                user_data = sync_level_from_exp(user_data)

                inventory = user_data.get("inventory", [])
                inventory.append(item)

                ref.update({
                    "points": user_data["points"],
                    "total_exp": user_data["total_exp"],
                    "exp": user_data["exp"],
                    "level": user_data["level"],
                    "inventory": inventory
                })

                reply = (
                    f"🎣 낚시 성공!\n"
                    f"획득: {format_item(item)}\n"
                    f"+{gained_points} 포인트\n"
                    f"+{gained_exp} EXP"
                )
                if user_data["level"] > old_level:
                    reply += f"\n🎉 레벨업! Lv.{old_level} → Lv.{user_data['level']}"

        elif msg == "!광산":
            user_data, ref = ensure_user(room, sender)
            ok, remain = use_activity_cooldown(user_data, ref, "last_mine_at", MINE_COOLDOWN_SEC)

            if not ok:
                reply = f"⏳ 광산은 조금 쉬었다가 해줘. {remain}초 남음"
            else:
                item = pick_mine_drop()
                gained_points = random.randint(10, 35)
                gained_exp = random.randint(8, 20)

                user_data["points"] = int(user_data.get("points", 0)) + gained_points
                user_data["total_exp"] = int(user_data.get("total_exp", 0)) + gained_exp
                old_level = int(user_data.get("level", 1))
                user_data = sync_level_from_exp(user_data)

                inventory = user_data.get("inventory", [])
                inventory.append(item)

                ref.update({
                    "points": user_data["points"],
                    "total_exp": user_data["total_exp"],
                    "exp": user_data["exp"],
                    "level": user_data["level"],
                    "inventory": inventory
                })

                reply = (
                    f"⛏ 채굴 성공!\n"
                    f"획득: {format_item(item)}\n"
                    f"+{gained_points} 포인트\n"
                    f"+{gained_exp} EXP"
                )
                if user_data["level"] > old_level:
                    reply += f"\n🎉 레벨업! Lv.{old_level} → Lv.{user_data['level']}"

        # =========================
        # 상점 / 판매
        # =========================
        elif msg == "!상점":
            lines = ["🛒 상점"]
            for name, info in SHOP_ITEMS.items():
                lines.append(f"- {name} | {info['price']}포인트 | {info['desc']}")
            reply = "\n".join(lines)

        elif msg.startswith("!구매 "):
            user_data, ref = ensure_user(room, sender)
            item_name = msg.replace("!구매 ", "").strip()

            if item_name not in SHOP_ITEMS:
                reply = "상점에 없는 아이템이야."
            else:
                info = SHOP_ITEMS[item_name]
                price = int(info["price"])
                points = int(user_data.get("points", 0))

                if points < price:
                    reply = f"💰 포인트가 부족해. 필요 포인트: {price}"
                else:
                    new_item = make_item(item_name, info["type"], "common", sell_price=price // 2)
                    inventory = user_data.get("inventory", [])
                    inventory.append(new_item)
                    new_points = points - price

                    ref.update({
                        "points": new_points,
                        "inventory": inventory
                    })

                    reply = f"🛒 구매 완료!\n아이템: {item_name}\n남은 포인트: {new_points}"

        elif msg == "!판매 전부":
            user_data, ref = ensure_user(room, sender)
            inventory = user_data.get("inventory", [])

            if not inventory:
                reply = "판매할 아이템이 없어."
            else:
                total = sum(get_sell_price(item) for item in inventory)
                new_points = int(user_data.get("points", 0)) + total
                ref.update({
                    "points": new_points,
                    "inventory": []
                })
                reply = f"💸 인벤토리 전체 판매 완료!\n획득 포인트: {total}\n현재 포인트: {new_points}"

        elif msg.startswith("!판매 "):
            user_data, ref = ensure_user(room, sender)
            parts = msg.split()

            if len(parts) != 2:
                reply = "사용법: !판매 번호"
            else:
                try:
                    idx = int(parts[1]) - 1
                    inventory = user_data.get("inventory", [])

                    if idx < 0 or idx >= len(inventory):
                        reply = "없는 인벤토리 번호야."
                    else:
                        item = inventory[idx]
                        price = get_sell_price(item)
                        new_inventory = inventory[:]
                        new_inventory.pop(idx)
                        new_points = int(user_data.get("points", 0)) + price

                        ref.update({
                            "inventory": new_inventory,
                            "points": new_points
                        })

                        reply = f"💸 판매 완료!\n아이템: {format_item(item)}\n획득 포인트: {price}\n현재 포인트: {new_points}"
                except ValueError:
                    reply = "번호를 올바르게 입력해줘."

        # =========================
        # 놀이
        # =========================
        elif msg == "!주사위":
            reply = f"🎲 주사위 결과: {random.randint(1, 6)}"

        elif msg == "!동전":
            reply = f"🪙 동전 결과: {random.choice(['앞면', '뒷면'])}"

        elif msg == "!운세":
            fortunes = [
                "오늘은 운이 좋아!",
                "좋은 일이 생길 가능성이 커!",
                "무리하지 않으면 괜찮은 하루야.",
                "뜻밖의 연락이 올 수도 있어.",
                "작은 선택이 큰 차이를 만들 수 있어."
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
                reply = f"✌ 너: {user_pick}\n🤖 봇: {bot_pick}\n📢 결과: {result}"

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
                        reply = f"🎯 {min_num}~{max_num} 사이 랜덤 숫자: {random.randint(min_num, max_num)}"
                except ValueError:
                    reply = "숫자를 올바르게 입력해줘."

        elif msg == "!오늘의음식":
            foods = ["치킨", "떡볶이", "피자", "햄버거", "라면", "돈까스", "국밥", "마라탕"]
            reply = f"🍽 오늘의 음식 추천: {random.choice(foods)}"

        elif msg == "!뽑기":
            items = ["꽝", "꽝", "소소한 행운", "간식 당첨", "대박 당첨", "완전 럭키"]
            reply = f"🎁 뽑기 결과: {random.choice(items)}"

        # =========================
        # 관리자
        # =========================
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
                            reply = f"🛠 {target_name}님 레벨을 {add_level_num} 올렸어!\n현재 레벨: Lv.{new_level}"
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
                            target_ref.update({"points": new_points})
                            reply = f"💰 {target_name}님에게 {add_points_num} 포인트 지급!\n현재 포인트: {new_points}"
                    except ValueError:
                        reply = "숫자를 올바르게 입력해줘."

        return jsonify({"reply": reply})

    except Exception as e:
        print("BOT ERROR:", str(e))
        return jsonify({"reply": "❌ 서버 내부 오류: " + str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
