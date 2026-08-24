import ftfy

with open('templates/03_upload.html', 'r', encoding='utf-8') as f:
    content = f.read()

fixed = ftfy.fix_text(content)

with open('templates/03_upload.html', 'w', encoding='utf-8') as f:
    f.write(fixed)

print('OK')