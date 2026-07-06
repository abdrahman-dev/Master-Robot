from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # للسماح بالاتصال من تطبيق فلاتر (خاصة عند استخدام المتصفح)

# بيانات افتراضية
battery_level = 88

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
    if params:
        print(f"📊 البيانات: {params}")

    # --- منطق التحكم ---
    if action == 'move':
        direction = params.get('direction')
        # هنا يمكنك إضافة كود GPIO للتحكم في المحركات
        return jsonify({"message": f"الروبوت يتحرك {direction}"})

    elif action == 'speak':
        text = params.get('text')
        # هنا يمكنك إضافة كود تحويل النص لصوت (TTS)
        print(f"🎙️ نطق النص: {text}")
        return jsonify({"message": "تم نطق النص بنجاح"})

    elif action == 'volume':
        state = params.get('state')
        return jsonify({"message": f"تعديل الصوت إلى: {state}"})

    elif action == 'power':
        if params.get('state') == 'off':
            print("🔌 إغلاق النظام...")
            return jsonify({"message": "جاري إغلاق الراسبري باي"})

    return jsonify({"status": "success", "message": f"تم تنفيذ {action}"})

if __name__ == '__main__':
    # تشغيل السيرفر على جميع عناوين الشبكة المحلية على المنفذ 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
