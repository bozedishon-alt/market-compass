# بوصلة السوق – التحديث التلقائي اليومي (مرة واحدة فقط تجهّزه)

1. أنشئ حساب مجاني في https://github.com ثم New repository (اسمه مثلاً market-compass، Public).
2. اضغط "uploading an existing file" وارفع كل محتويات هذا المجلد (بما فيها مجلد .github و docs).
3. Settings ← Pages ← Source: Deploy from a branch ← Branch: main ، Folder: /docs ← Save.
4. تبويب Actions ← daily-update ← Run workflow (يشغّله أول مرة). بعدها يشتغل لوحده كل يوم.
5. رابط موقعك يظهر في Settings ← Pages (شكله: https://اسمك.github.io/market-compass/).

اختياري (Settings ← Secrets and variables ← Actions ← New secret):
- NEWSAPI_KEY : مفتاح من newsapi.org (بدونه يستخدم GDELT المجاني)
- TELEGRAM_TOKEN و TELEGRAM_CHAT_ID : للتنبيه عند تغيّر أي إشارة
