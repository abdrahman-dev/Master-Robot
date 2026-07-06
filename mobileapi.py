from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # للسماح للتطبيق بالاتصال من المتصفح أو الهاتف

# --- إعدادات وهمية (يمكنك استبدالها بكود التحكم في المحركات لاحقاً) ---
battery_level = 85

@app.route('/battery', methods=['GET'])
def get_battery():
    """يرسل مستوى البطارية للتطبيق لتشغيل اللمبة (أخضر/أحمر)"""
    return jsonify({"level": battery_level})

@app.route('/command', methods=['POST'])
def handle_command():
    """يستقبل الأوامر من أزرار التطبيق والذكاء الاصطناعي"""
    data = request.json
    action = data.get('action')
    params = data.get('params', {})

    print(f"📡 أمر مستلم: {action}")
    print(f"📊 البيانات: {params}")

    if action == 'move':
        direction = params.get('direction')
        # هنا تضع كود تحريك المحركات (مثلاً باستخدام RPi.GPIO)
        return jsonify({"message": f"الروبوت يتحرك {direction}"})

    elif action == 'speak':
        text = params.get('text')
        # هنا تضع كود تحويل النص لصوت (TTS)
        print(f"🎙️ نطق النص: {text}")
        return jsonify({"message": "تم نطق النص بنجاح"})

    elif action == 'volume':
        state = params.get('state')
        return jsonify({"message": f"تعديل الصوت إلى: {state}"})

    elif action == 'power':
        if params.get('state') == 'off':
            print("🔌 إغلاق النظام...")
            return jsonify({"message": "جاري إغلاق الراسبري باي"})

    return jsonify({"message": "تم استلام الأمر بنجاح"})

if __name__ == '__main__':
    # تشغيل السيرفر على المنفذ 5000
    app.run(host='0.0.0.0', port=5000, debug=True)