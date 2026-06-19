from flask import Flask, request
import requests
import os

app = Flask(__name__)

BOT_TOKEN = "8886558665:AAEBUpBtax_rm4WqvjFDltTQ1gnMHYSwhDI"
CHAT_ID = "7492355509"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_data(as_text=True)
        
        message = f"🔔 NuSignal Bildirim\n\n{data}"
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message
        }
        requests.post(url, json=payload)
        
        return "OK", 200
    except Exception as e:
        return str(e), 500

@app.route('/', methods=['GET'])
def home():
    return "Bot calisiyor!", 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
