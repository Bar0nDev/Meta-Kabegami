from flask import Flask, render_template, send_from_directory, redirect, url_for, request, session, send_file, flash, \
    jsonify
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageOps, ImageDraw, ImageFilter
from bs4 import BeautifulSoup
from curl_cffi import requests
from io import BytesIO
import os
import json
import hashlib
import base64
import time
import uuid
import tempfile

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")

app.config['SESSION_PERMANENT'] = True
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

EDGE_CONFIG_TOKEN = os.getenv("EDGE_KEY")
EDGE_CONFIG_BASE_URL = "https://edge-config.vercel.com/v1"

DEVICE_SIZES = {
    'iphone_14_pro': (1179, 2556),
    'iphone_14': (1170, 2532),
    'iphone_13_pro': (1170, 2532),
    'iphone_12_pro': (1170, 2532),
    'iphone_x': (1125, 2436),
    'samsung_s23': (1080, 2340),
    'samsung_s22': (1080, 2340),
    'pixel_7': (1080, 2400),
}


def generate_cache_key(img_src, device_type, target_width, target_height):
    """Generate a unique cache key for the image configuration"""
    key_string = f"{img_src}_{device_type}_{target_width}_{target_height}"
    return hashlib.md5(key_string.encode()).hexdigest()


def generate_session_id():
    """Generate a unique session ID for file naming"""
    return str(uuid.uuid4())[:8]


def get_temp_dir():
    """Get a consistent temporary directory"""
    temp_dir = tempfile.gettempdir()
    return temp_dir


def cleanup_old_files():
    """Clean up old temporary files (older than 10 minutes)"""
    try:
        tmp_folder = get_temp_dir()
        current_time = time.time()

        for filename in os.listdir(tmp_folder):
            if filename.startswith(('image_converted_', 'target_img_', 'cached_')):
                file_path = os.path.join(tmp_folder, filename)
                if os.path.isfile(file_path):
                    if current_time - os.path.getmtime(file_path) > 600:
                        os.unlink(file_path)
    except Exception as e:
        print(f"Error cleaning up files: {e}")


def get_from_edge_config(key):
    """Retrieve data from Vercel Edge Config"""
    try:
        if not EDGE_CONFIG_TOKEN:
            print("No Edge Config token found")
            return None

        headers = {
            'Authorization': f'Bearer {EDGE_CONFIG_TOKEN}',
            'Content-Type': 'application/json'
        }

        response = requests.get(
            f"{EDGE_CONFIG_BASE_URL}/items/{key}",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            print(f"Cache key {key} not found")
            return None
        else:
            print(f"Edge Config error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error retrieving from Edge Config: {e}")
        return None


def save_to_edge_config(key, data):
    """Save data to Vercel Edge Config"""
    try:
        if not EDGE_CONFIG_TOKEN:
            print("No Edge Config token found")
            return False

        headers = {
            'Authorization': f'Bearer {EDGE_CONFIG_TOKEN}',
            'Content-Type': 'application/json'
        }

        payload = {key: data}

        response = requests.patch(
            f"{EDGE_CONFIG_BASE_URL}/items",
            headers=headers,
            json=payload,
            timeout=10
        )

        if response.status_code in [200, 201]:
            print(f"Successfully saved cache key: {key}")
            return True
        else:
            print(f"Failed to save to Edge Config: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"Error saving to Edge Config: {e}")
        return False


def image_to_base64(image_path):
    """Convert image file to base64 string"""
    try:
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
            base64_str = base64.b64encode(image_data).decode('utf-8')
            print(f"Image converted to base64, size: {len(base64_str)} chars")
            return base64_str
    except Exception as e:
        print(f"Error converting image to base64: {e}")
        return None


def base64_to_image(base64_string, output_path):
    """Convert base64 string back to image file"""
    try:
        if not base64_string:
            print("Empty base64 string")
            return False

        image_data = base64.b64decode(base64_string)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "wb") as image_file:
            image_file.write(image_data)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"Successfully created image at: {output_path}")
            return True
        else:
            print(f"Failed to create image at: {output_path}")
            return False
    except Exception as e:
        print(f"Error converting base64 to image: {e}")
        return False


def get_device_dimensions(device_type, custom_width=None, custom_height=None):
    """Get device dimensions based on selection"""
    if device_type == 'custom':
        if custom_width and custom_height:
            try:
                width = int(custom_width)
                height = int(custom_height)
                if 200 <= width <= 5000 and 200 <= height <= 8000:
                    return width, height
                else:
                    raise ValueError("Dimensions out of reasonable range")
            except (ValueError, TypeError):
                return None, None
        else:
            return None, None

    return DEVICE_SIZES.get(device_type, (1125, 2436))


def create_wallpaper(img, target_width, target_height):
    """Create wallpaper with specified dimensions"""
    pix = img.load()
    palette_rgb = pix[30, 1] if img.width > 30 else pix[0, 0]

    if img.height > 20:
        cropped_img = img.crop((0, 20, img.width, img.height))
    else:
        cropped_img = img

    main_img_height = int(target_height * 0.7)
    gradient_height = target_height - main_img_height

    resized_img = ImageOps.fit(cropped_img, size=(target_width, main_img_height))

    final_img = Image.new('RGB', (target_width, target_height), color=palette_rgb)

    final_img.paste(resized_img, (0, gradient_height))

    for y in range(gradient_height):
        opacity = 1.0 - (y / gradient_height)
        gradient_intensity = int(255 * opacity * 0.3)

        blended_color = (
            max(0, palette_rgb[0] - gradient_intensity),
            max(0, palette_rgb[1] - gradient_intensity),
            max(0, palette_rgb[2] - gradient_intensity)
        )

        draw = ImageDraw.Draw(final_img)
        draw.line([(0, y), (target_width, y)], fill=blended_color)

    seam_y = gradient_height
    blur_zone_height = min(150, gradient_height // 3)

    if blur_zone_height > 0:
        blur_start_y = max(0, seam_y - blur_zone_height // 2)
        blur_end_y = min(target_height, seam_y + blur_zone_height // 2)

        if blur_end_y > blur_start_y:
            blur_zone = final_img.crop((0, blur_start_y, target_width, blur_end_y))
            blur_radius = min(25, blur_zone_height // 6)
            blurred = blur_zone.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            final_img.paste(blurred, (0, blur_start_y))

    return final_img


def ensure_image_exists(session_id, cache_key=None):
    """Ensure the image file exists, recreate from cache if necessary"""
    temp_dir = get_temp_dir()
    expected_path = os.path.join(temp_dir, f'image_converted_{session_id}.png')

    if os.path.exists(expected_path) and os.path.getsize(expected_path) > 0:
        print(f"Image file exists at: {expected_path}")
        return expected_path

    if cache_key:
        print(f"Attempting to recreate image from cache: {cache_key}")
        cached_data = get_from_edge_config(cache_key)
        if cached_data and 'image_base64' in cached_data:
            success = base64_to_image(cached_data['image_base64'], expected_path)
            if success:
                print("Successfully recreated image from cache")
                return expected_path
            else:
                print("Failed to recreate image from cache")

    print(f"Image not found and couldn't be recreated: {expected_path}")
    return None


@app.route('/', methods=["POST", "GET"])
def main_page():
    if request.method == "GET":
        cleanup_old_files()
        return render_template('index.html')
    else:
        img_address = request.form['pname']
        device_type = request.form.get('device', 'iphone_x')
        custom_width = request.form.get('custom_width')
        custom_height = request.form.get('custom_height')

        target_width, target_height = get_device_dimensions(device_type, custom_width, custom_height)

        if target_width is None or target_height is None:
            flash('Invalid device dimensions. Please check your custom size values.', 'error')
            return render_template('index.html')

        try:
            session_id = generate_session_id()
            session['session_id'] = session_id
            session.permanent = True

            print(f"Generated session ID: {session_id}")

            response = requests.get(img_address, timeout=15)
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')

            if response.status_code == 200:
                img_tag = soup.find("meta", property="og:image")
                title_tag = soup.find("meta", property="og:title")

                if img_tag and title_tag:
                    img_src = img_tag["content"]
                    title = title_tag["content"]

                    print(f"Found image: {img_src}")
                    print(f"Found title: {title}")

                    cache_key = generate_cache_key(img_src, device_type, target_width, target_height)
                    print(f"Generated cache key: {cache_key}")

                    temp_dir = get_temp_dir()
                    converted_path = os.path.join(temp_dir, f'image_converted_{session_id}.png')
                    target_path = os.path.join(temp_dir, f'target_img_{session_id}.png')

                    cached_data = get_from_edge_config(cache_key)

                    if cached_data and 'image_base64' in cached_data:
                        print("Loading wallpaper from cache...")
                        success = base64_to_image(cached_data['image_base64'], converted_path)

                        if success:
                            session['title'] = cached_data.get('title', title)
                            session['img_src'] = cached_data.get('img_src', img_src)
                            session['device_type'] = device_type
                            session['dimensions'] = f"{target_width} × {target_height}"
                            session['cache_key'] = cache_key
                            session['image_path'] = converted_path
                            session['from_cache'] = True

                            print("Successfully loaded from cache, redirecting...")
                            return redirect('/create')
                        else:
                            print("Failed to load from cache, generating new...")

                    print("Generating new wallpaper...")
                    img_response = requests.get(img_src, timeout=15)

                    if img_response.status_code != 200:
                        raise Exception(f"Failed to download image: {img_response.status_code}")

                    img = Image.open(BytesIO(img_response.content))
                    print(f"Original image size: {img.size}")

                    img.save(target_path)
                    print(f"Saved original image to: {target_path}")

                    final_img = create_wallpaper(img, target_width, target_height)
                    final_img.save(converted_path)
                    print(f"Created wallpaper at: {converted_path}")

                    if not os.path.exists(converted_path) or os.path.getsize(converted_path) == 0:
                        raise Exception("Failed to create wallpaper image")

                    try:
                        image_base64 = image_to_base64(converted_path)
                        if image_base64:
                            cache_data = {
                                'image_base64': image_base64,
                                'title': title,
                                'img_src': img_src,
                                'device_type': device_type,
                                'target_width': target_width,
                                'target_height': target_height,
                                'created_at': datetime.now().isoformat()
                            }

                            save_success = save_to_edge_config(cache_key, cache_data)
                            if save_success:
                                print("Wallpaper saved to cache successfully!")
                            else:
                                print("Failed to save wallpaper to cache (continuing anyway)")
                    except Exception as cache_error:
                        print(f"Cache save error (continuing anyway): {cache_error}")

                    session['title'] = title
                    session['img_src'] = img_src
                    session['device_type'] = device_type
                    session['dimensions'] = f"{target_width} × {target_height}"
                    session['cache_key'] = cache_key
                    session['image_path'] = converted_path
                    session['from_cache'] = False

                    print("Session data stored, redirecting to create page...")
                    return redirect('/create')
                else:
                    flash('Unable to retrieve NFT details. Please check the link and try again.', 'error')
                    return render_template('index.html')
            else:
                flash(f'Unable to retrieve NFT details. HTTP {response.status_code}', 'error')
                return render_template('index.html')

        except Exception as e:
            print(f"Error in main_page: {str(e)}")
            flash(f'An error occurred: {str(e)}', 'error')
            return render_template('index.html')


@app.route('/image/<filename>')
def get_image(filename):
    """Serve images from session-specific files"""
    session_id = session.get('session_id')
    if not session_id:
        print("No session ID found")
        return "Session expired", 404

    if filename == 'image_converted.png':
        actual_filename = f'image_converted_{session_id}.png'
    else:
        actual_filename = filename

    temp_dir = get_temp_dir()
    file_path = os.path.join(temp_dir, actual_filename)

    print(f"Looking for image at: {file_path}")

    if not os.path.exists(file_path):
        print(f"Image not found, attempting to recreate...")
        cache_key = session.get('cache_key')
        if cache_key:
            image_path = ensure_image_exists(session_id, cache_key)
            if image_path:
                return send_from_directory(temp_dir, actual_filename)

        print("Could not find or recreate image")
        return "Image not found", 404

    return send_from_directory(temp_dir, actual_filename)


@app.route('/cached-image/<cache_key>')
def get_cached_image(cache_key):
    """Serve image directly from Edge Config cache"""
    try:
        cached_data = get_from_edge_config(cache_key)

        if cached_data and 'image_base64' in cached_data:
            session_id = session.get('session_id', 'temp')
            temp_dir = get_temp_dir()
            temp_path = os.path.join(temp_dir, f'cached_{session_id}_{cache_key}.png')
            success = base64_to_image(cached_data['image_base64'], temp_path)

            if success:
                return send_file(temp_path, mimetype='image/png')

        return redirect(url_for('get_image', filename='image_converted.png'))
    except Exception as e:
        print(f"Error serving cached image: {e}")
        return redirect(url_for('get_image', filename='image_converted.png'))


@app.route('/create', methods=["POST", "GET"])
def create_page():
    if request.method == "GET":
        print(f"Session data: {dict(session)}")

        required_keys = ['title', 'img_src', 'session_id']
        missing_keys = [key for key in required_keys if key not in session]

        if missing_keys:
            print(f"Missing session keys: {missing_keys}")
            flash('Session expired. Please generate a new wallpaper.', 'error')
            return redirect(url_for('main_page'))

        session_id = session.get('session_id')
        cache_key = session.get('cache_key')

        image_path = ensure_image_exists(session_id, cache_key)
        if not image_path:
            flash('Unable to load wallpaper. Please generate a new one.', 'error')
            return redirect(url_for('main_page'))

        return render_template('create.html',
                               img_src=session['img_src'],
                               art_title=session['title'],
                               device_type=session.get('device_type', 'Unknown'),
                               dimensions=session.get('dimensions', 'Unknown'),
                               cache_key=session.get('cache_key', ''),
                               from_cache=session.get('from_cache', False),
                               time_now=datetime.now().timestamp())


@app.route('/download')
def download_page():
    session_id = session.get('session_id')
    if not session_id:
        flash('Session expired. Please generate a new wallpaper.', 'error')
        return redirect(url_for('main_page'))

    cache_key = session.get('cache_key')
    image_path = ensure_image_exists(session_id, cache_key)

    if not image_path:
        flash('No wallpaper found. Please generate a new one.', 'error')
        return redirect(url_for('main_page'))

    device_type = session.get('device_type', 'wallpaper')
    title = session.get('title', 'nft_wallpaper')
    clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    clean_title = clean_title.replace(' ', '_')[:30]

    filename = f"{clean_title}_{device_type}_wallpaper.png"

    return send_file(image_path, as_attachment=True, download_name=filename)


@app.route('/debug')
def debug_page():
    """Debug endpoint to check session and file status"""
    session_id = session.get('session_id')
    temp_dir = get_temp_dir()

    debug_info = {
        'session_id': session_id,
        'session_data': dict(session),
        'temp_dir': temp_dir,
        'files': []
    }

    if session_id:
        expected_path = os.path.join(temp_dir, f'image_converted_{session_id}.png')
        debug_info['expected_path'] = expected_path
        debug_info['file_exists'] = os.path.exists(expected_path)
        if os.path.exists(expected_path):
            debug_info['file_size'] = os.path.getsize(expected_path)

    try:
        for filename in os.listdir(temp_dir):
            if filename.startswith(('image_converted_', 'target_img_', 'cached_')):
                file_path = os.path.join(temp_dir, filename)
                debug_info['files'].append({
                    'filename': filename,
                    'size': os.path.getsize(file_path),
                    'modified': os.path.getmtime(file_path)
                })
    except Exception as e:
        debug_info['list_error'] = str(e)

    return jsonify(debug_info)


if __name__ == '__main__':
    app.run(debug=True)