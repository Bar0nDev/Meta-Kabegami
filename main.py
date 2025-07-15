from flask import Flask, render_template, send_from_directory, redirect, url_for, request, session, send_file, flash
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageOps, ImageDraw, ImageFilter
from bs4 import BeautifulSoup
from curl_cffi import requests
from io import BytesIO
import os

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")


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


@app.route('/', methods=["POST", "GET"])
def main_page():
    if request.method == "GET":
        tmp_folder = '/tmp'
        try:
            for filename in os.listdir(tmp_folder):
                file_path = os.path.join(tmp_folder, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
        except Exception as e:
            print(e)
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
            response = requests.get(img_address)
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')

            if response.status_code == 200:
                img_tag = soup.find("meta", property="og:image")
                title_tag = soup.find("meta", property="og:title")

                if img_tag and title_tag:
                    img_src = img_tag["content"]
                    title = title_tag["content"]

                    img_response = requests.get(img_src)
                    img = Image.open(BytesIO(img_response.content))

                    img.save("/tmp/target_img.png")

                    final_img = create_wallpaper(img, target_width, target_height)

                    final_img.save('/tmp/image_converted.png')

                    session['title'] = title
                    session['img_src'] = img_src
                    session['device_type'] = device_type
                    session['dimensions'] = f"{target_width} × {target_height}"

                    return redirect('/create')
                else:
                    flash('Unable to retrieve NFT details. Please check the link and try again.', 'error')
                    return render_template('index.html')
            else:
                flash('Unable to retrieve NFT details. Please check the link and try again.', 'error')
                return render_template('index.html')

        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'error')
            return render_template('index.html')


@app.route('/image/<filename>')
def get_image(filename):
    return send_from_directory('/tmp', filename)


@app.route('/create', methods=["POST", "GET"])
def create_page():
    if request.method == "GET":
        if 'title' not in session or 'img_src' not in session:
            flash('Session expired. Please generate a new wallpaper.', 'error')
            return redirect(url_for('main_page'))

        return render_template('create.html',
                               img_src=session['img_src'],
                               art_title=session['title'],
                               device_type=session.get('device_type', 'Unknown'),
                               dimensions=session.get('dimensions', 'Unknown'),
                               time_now=datetime.now().timestamp())


@app.route('/download')
def download_page():
    path = "/tmp/image_converted.png"
    if not os.path.exists(path):
        flash('No wallpaper found. Please generate a new one.', 'error')
        return redirect(url_for('main_page'))

    device_type = session.get('device_type', 'wallpaper')
    title = session.get('title', 'nft_wallpaper')
    clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
    clean_title = clean_title.replace(' ', '_')[:30]

    filename = f"{clean_title}_{device_type}_wallpaper.png"

    return send_file(path, as_attachment=True, download_name=filename)


if __name__ == '__main__':
    app.run(debug=True)