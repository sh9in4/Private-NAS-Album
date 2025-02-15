import os
import shutil
import json
from flask import Flask, render_template, request, jsonify
from smb.SMBConnection import SMBConnection
from PIL import Image
from PIL.ExifTags import TAGS
from configparser import ConfigParser

# 設定ファイルの読み込み
config = ConfigParser()
config.read('config.ini')

# Flask アプリケーションの初期化
app = Flask(__name__)

# NASのSMB設定
NAS_SERVER = config['NAS']['SERVER']  # NASのIPアドレス
NAS_SHARE = config['NAS']['SHARE']   # NASの共有フォルダ名
NAS_USER = config['NAS']['USER']     # NASのユーザー名
NAS_PASSWORD = config['NAS']['PASSWORD']  # NASのパスワード

BASE_FOLDER = "PHOTO"

# 一時保存用のローカルディレクトリ
LOCAL_IMAGE_DIR = os.path.join("static", "images")
os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)  # 一時保存ディレクトリを作成

# フォルダリストをキャッシュするファイル
CACHE_FILE = "folder_cache.json"

def save_cache(data):
    """フォルダリストをキャッシュとして保存"""
    with open(CACHE_FILE, 'w') as f:
        json.dump(data, f)

def load_cache():
    """キャッシュされたフォルダリストをロード"""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return None

def get_image_exif(image_path):
    """画像のExif情報を取得し、撮影日を返す"""
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()
        
        if exif_data:
            for tag, value in exif_data.items():
                if TAGS.get(tag) == 'DateTimeOriginal':
                    return value  # DateTimeOriginal（撮影日）を返す
    except Exception as e:
        print(f"Exifデータの取得に失敗しました: {e}")
    return None  # Exifデータが取得できない場合はNoneを返す

def get_folder_list(path="", max_depth=3, current_depth=0):
    """NAS上のフォルダ一覧と各フォルダ内の画像ファイル数を取得（再帰的）"""
    # キャッシュがあれば、それを返す
    cached_folders = load_cache()
    if cached_folders:
        return cached_folders

    conn = SMBConnection(NAS_USER, NAS_PASSWORD, "flask_app", "NAS", use_ntlm_v2=True)
    assert conn.connect(NAS_SERVER, 139)

    folders = []
    files = conn.listPath(NAS_SHARE, f"/{BASE_FOLDER}/{path}")

    for file in files:
        if file.isDirectory and not file.filename.startswith("."):  # 「.」で始まる隠しフォルダを除外
            subfolder_path = f"{path}/{file.filename}" if path else file.filename
            # 各フォルダ内の画像ファイル数を取得
            folder_files = conn.listPath(NAS_SHARE, f"/{BASE_FOLDER}/{subfolder_path}")
            image_count = len([
                f for f in folder_files
                if not f.isDirectory and not f.filename.startswith("._") and f.filename.lower().endswith(('.jpg', '.jpeg', '.png'))
            ])
            folders.append({"name": subfolder_path, "file_count": image_count})

            # 最大階層数に達していない場合に再帰的にサブフォルダを取得
            if current_depth < max_depth:
                folders.extend(get_folder_list(subfolder_path, max_depth, current_depth + 1))

    conn.close()
    
    # フォルダリストをキャッシュとして保存
    save_cache(folders)
    
    return folders


def fetch_images_from_nas(folder_path):
    """NASから指定フォルダ内の画像ファイルを取得"""
    conn = SMBConnection(NAS_USER, NAS_PASSWORD, "flask_app", "NAS", use_ntlm_v2=True)
    assert conn.connect(NAS_SERVER, 139)

    files = conn.listPath(NAS_SHARE, f"/{BASE_FOLDER}/{folder_path}")
    image_files = []

    for file in files:
        if not file.isDirectory and not file.filename.startswith("._") and file.filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            local_image_path = os.path.join(LOCAL_IMAGE_DIR, file.filename)
            # NASからローカルに画像をコピー
            with open(local_image_path, "wb") as f:
                conn.retrieveFile(NAS_SHARE, f"/{BASE_FOLDER}/{folder_path}/{file.filename}", f)
            
            # Exif情報から撮影日を取得
            shooting_date = get_image_exif(local_image_path)
            image_files.append({
                'filename': file.filename,
                'shooting_date': shooting_date
            })

    conn.close()
    return image_files

@app.route("/", methods=["GET", "POST"])
def index():
    """画像一覧を表示するメインページ"""
    folder_list = get_folder_list(max_depth=0)  # NAS上のフォルダ一覧を取得
    image_files = []
    selected_folder = ""

    if request.method == "POST":
        # プルダウンから選択されたフォルダを取得
        selected_folder = request.form.get("folder", "").strip()
        if selected_folder:
            try:
                # NASから画像を取得
                image_files = fetch_images_from_nas(selected_folder)
            except Exception as e:
                print(f"Error fetching images from {selected_folder}: {e}")

    return render_template("index.html", folder_list=folder_list, image_files=image_files, selected_folder=selected_folder)

@app.route("/get_subfolders", methods=["GET"])
def get_subfolders():
    """選択したフォルダのサブフォルダを取得"""
    folder = request.args.get("folder")
    subfolders = get_folder_list(folder)
    return jsonify({"subfolders": subfolders})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)