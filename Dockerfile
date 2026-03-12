# Pythonの軽いバージョンをベースにする
FROM python:3.10-slim

# アプリを置くフォルダを指定
WORKDIR /app

# GitHubにあるファイルをすべてコンテナの中にコピー
COPY . ./

# 必要な部品（requirements.txtに書いたもの）をインストール
RUN pip install --no-cache-dir -r requirements.txt

# Google Cloud Runが使うポート番号(8080)を開ける
EXPOSE 8080

# アプリを起動する命令（ポート8080を指定）
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
