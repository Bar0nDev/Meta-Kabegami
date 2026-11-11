from flask import Flask, render_template, send_from_directory, redirect, url_for, request, session, send_file, flash
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageOps, ImageDraw, ImageFilter
from bs4 import BeautifulSoup
from curl_cffi import requests
from io import BytesIO
import os
from urllib.parse import quote

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY")
OPENSEA_API_KEY = os.getenv('OPENSEA_API_KEY')
OPENSEA_API_BASE_URL = 'https://api.opensea.io/api/v2'


DEVICE_SIZES = {
    'iphone_16_pro_max': (1320, 2868),
    'iphone_16_pro': (1206, 2622),
    'iphone_15_pro_max': (1290, 2796),
    'iphone_15_pro': (1179, 2556),
    'iphone_14_pro': (1179, 2556),
    'iphone_14': (1170, 2532),
    'iphone_13_pro': (1170, 2532),
    'iphone_12_pro': (1170, 2532),
    'iphone_x': (1125, 2436),
    'samsung_s24_ultra': (1440, 3120),
    'samsung_s24': (1080, 2340),
    'samsung_s23': (1080, 2340),
    'samsung_s22': (1080, 2340),
    'pixel_9_pro_xl': (1344, 2992),
    'pixel_7': (1080, 2400),
    'oneplus_12': (1440, 3168),
}

DEVICE_OPTIONS = [
    {'value': 'iphone_16_pro_max', 'label': 'iPhone 16 Pro Max', 'dimensions': '1320 × 2868'},
    {'value': 'iphone_16_pro', 'label': 'iPhone 16 Pro', 'dimensions': '1206 × 2622'},
    {'value': 'iphone_15_pro_max', 'label': 'iPhone 15 Pro Max', 'dimensions': '1290 × 2796'},
    {'value': 'iphone_15_pro', 'label': 'iPhone 15 Pro', 'dimensions': '1179 × 2556'},
    {'value': 'iphone_14_pro', 'label': 'iPhone 14 Pro', 'dimensions': '1179 × 2556'},
    {'value': 'iphone_14', 'label': 'iPhone 14', 'dimensions': '1170 × 2532'},
    {'value': 'iphone_13_pro', 'label': 'iPhone 13 Pro', 'dimensions': '1170 × 2532'},
    {'value': 'iphone_12_pro', 'label': 'iPhone 12 Pro', 'dimensions': '1170 × 2532'},
    {'value': 'iphone_x', 'label': 'iPhone X', 'dimensions': '1125 × 2436'},
    {'value': 'samsung_s24_ultra', 'label': 'Samsung S24 Ultra', 'dimensions': '1440 × 3120'},
    {'value': 'samsung_s24', 'label': 'Samsung S24', 'dimensions': '1080 × 2340'},
    {'value': 'samsung_s23', 'label': 'Samsung S23', 'dimensions': '1080 × 2340'},
    {'value': 'samsung_s22', 'label': 'Samsung S22', 'dimensions': '1080 × 2340'},
    {'value': 'pixel_9_pro_xl', 'label': 'Google Pixel 9 Pro XL', 'dimensions': '1344 × 2992'},
    {'value': 'pixel_7', 'label': 'Google Pixel 7', 'dimensions': '1080 × 2400'},
    {'value': 'oneplus_12', 'label': 'OnePlus 12', 'dimensions': '1440 × 3168'},
    {'value': 'custom', 'label': 'Custom size', 'dimensions': 'Set your own'},
]

GRADIENT_STYLES = {
    'none': 0.0,
    'soft': 0.30,
    'strong': 0.55,
}

def catalog_context():
    return {'device_options': DEVICE_OPTIONS}


def render_home():
    live_collections, _ = list_opensea_collections()
    return render_template(
        'index.html',
        **catalog_context(),
        live_collections=(live_collections or [])[:3],
        opensea_configured=bool(OPENSEA_API_KEY),
    )


def opensea_get(path, params=None):
    """Read public marketplace data without exposing the API key to visitors."""
    if not OPENSEA_API_KEY:
        return None

    try:
        response = requests.get(
            f'{OPENSEA_API_BASE_URL}{path}',
            headers={'x-api-key': OPENSEA_API_KEY, 'accept': 'application/json'},
            params=params or {},
            timeout=10,
        )
        if response.status_code != 200:
            return None
        return response.json()
    except Exception as error:
        print(f'OpenSea request failed: {error}')
        return None


def normalize_opensea_collection(collection):
    slug = collection.get('collection') or collection.get('slug') or ''
    if not slug:
        return None

    return {
        'kind': 'collection',
        'id': f'collection:{slug}',
        'name': collection.get('name') or slug.replace('-', ' ').title(),
        'collection': 'OpenSea collection',
        'collection_slug': slug,
        'image': collection.get('image_url') or collection.get('banner_image_url') or '/static/images/logo.png',
        'description': collection.get('description') or 'Browse this collection on OpenSea.',
        'source_url': collection.get('opensea_url') or f'https://opensea.io/collection/{slug}',
    }


def normalize_opensea_nft(nft):
    identifier = nft.get('identifier') or nft.get('token_id') or ''
    contract = nft.get('contract') or ''
    if not identifier:
        return None

    collection_slug = nft.get('collection') or 'opensea'
    return {
        'kind': 'nft',
        'id': f'opensea:{contract}:{identifier}',
        'name': nft.get('name') or f'NFT #{identifier}',
        'collection': collection_slug.replace('-', ' ').title(),
        'collection_slug': collection_slug,
        'image': nft.get('image_url') or nft.get('display_image_url') or nft.get('image_original_url') or '',
        'image_url': nft.get('image_url') or nft.get('display_image_url') or nft.get('image_original_url') or '',
        'source_url': nft.get('opensea_url') or f'https://opensea.io/assets/{nft.get("chain", "ethereum")}/{contract}/{identifier}',
    }


def search_opensea(query, next_token=''):
    params = [
        ('query', query),
        ('asset_types', 'collection'),
        ('asset_types', 'nft'),
        ('limit', 50),
    ]
    if next_token:
        params.append(('next', next_token))

    payload = opensea_get('/search', params)
    if payload is None:
        return None, None

    results = []
    for result in payload.get('results', []):
        result_type = result.get('type')
        normalized = None
        if result_type == 'collection':
            normalized = normalize_opensea_collection(result.get('collection') or {})
        elif result_type == 'nft':
            normalized = normalize_opensea_nft(result.get('nft') or {})
        if normalized and normalized.get('image'):
            results.append(normalized)
    return results, payload.get('next')


def list_opensea_collections(next_token=''):
    params = [('limit', 50), ('chain', 'ethereum'), ('order_by', 'seven_day_volume')]
    if next_token:
        params.append(('next', next_token))
    payload = opensea_get('/collections', params)
    if payload is None:
        return None, None

    results = [normalize_opensea_collection(item) for item in payload.get('collections', [])]
    return [item for item in results if item and item.get('image')], payload.get('next')


def get_opensea_collection(slug):
    payload = opensea_get(f'/collections/{quote(slug, safe="")}')
    if not payload:
        return None
    return normalize_opensea_collection(payload)


def list_opensea_collection_nfts(slug, next_token=''):
    params = [('limit', 50)]
    if next_token:
        params.append(('next', next_token))
    payload = opensea_get(f'/collection/{quote(slug, safe="")}/nfts', params)
    if payload is None:
        return None, None

    results = [normalize_opensea_nft(item) for item in payload.get('nfts', [])]
    return [item for item in results if item and item.get('image')], payload.get('next')


def get_device_dimensions(device_type, custom_width=None, custom_height=None):
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


def get_art_scale(value):
    try:
        scale = int(value)
    except (TypeError, ValueError):
        return 100
    return max(60, min(140, scale))


def load_logo_image(logo_url):
    if not logo_url:
        return None

    if logo_url.startswith('/static/'):
        logo_path = os.path.join(app.root_path, logo_url.lstrip('/').replace('/', os.sep))
        with Image.open(logo_path) as logo:
            return logo.convert('RGBA')

    if not logo_url.startswith(('http://', 'https://')):
        raise ValueError('Collection logo must be a full image URL.')

    response = requests.get(logo_url, timeout=10)
    if response.status_code != 200:
        raise ValueError('The collection logo could not be downloaded.')
    with Image.open(BytesIO(response.content)) as logo:
        return logo.convert('RGBA')


def create_wallpaper(img, target_width, target_height, gradient_style='soft', collection_logo=None, art_scale=100):
    pix = img.load()
    palette_rgb = pix[30, 1] if img.width > 30 else pix[0, 0]

    if img.height > 20:
        cropped_img = img.crop((0, 20, img.width, img.height))
    else:
        cropped_img = img


    main_img_height = int(target_height * 0.7)
    gradient_height = target_height - main_img_height

    scale = get_art_scale(art_scale) / 100
    art_width = max(1, int(target_width * scale))
    art_height = max(1, int(main_img_height * scale))
    resized_img = ImageOps.fit(cropped_img, size=(art_width, art_height))

    final_img = Image.new('RGB', (target_width, target_height), color=palette_rgb)

    art_x = (target_width - art_width) // 2
    art_y = gradient_height + (main_img_height - art_height) // 2
    final_img.paste(resized_img, (art_x, art_y))

    gradient_strength = GRADIENT_STYLES.get(gradient_style, GRADIENT_STYLES['soft'])
    if gradient_strength > 0:
        for y in range(gradient_height):
            opacity = 1.0 - (y / gradient_height)
            gradient_intensity = int(255 * opacity * gradient_strength)

            blended_color = (
                max(0, palette_rgb[0] - gradient_intensity),
                max(0, palette_rgb[1] - gradient_intensity),
                max(0, palette_rgb[2] - gradient_intensity)
            )

            draw = ImageDraw.Draw(final_img)
            draw.line([(0, y), (target_width, y)], fill=blended_color)


    seam_y = gradient_height
    blur_zone_height = min(150, gradient_height // 3)

    if gradient_strength > 0 and blur_zone_height > 0:
        blur_start_y = max(0, seam_y - blur_zone_height // 2)
        blur_end_y = min(target_height, seam_y + blur_zone_height // 2)

        if blur_end_y > blur_start_y:
            blur_zone = final_img.crop((0, blur_start_y, target_width, blur_end_y))
            blur_radius = min(25, blur_zone_height // 6)
            blurred = blur_zone.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            final_img.paste(blurred, (0, blur_start_y))

    if collection_logo is not None:
        logo = collection_logo.copy().convert('RGBA')
        max_logo_size = max(96, int(min(target_width, target_height) * 0.14))
        logo.thumbnail((max_logo_size, max_logo_size), Image.Resampling.LANCZOS)
        margin = max(28, int(min(target_width, target_height) * 0.045))
        logo_x = target_width - logo.width - margin
        logo_y = margin
        plate_padding = max(14, int(max_logo_size * 0.12))
        plate = Image.new('RGBA', (logo.width + plate_padding * 2, logo.height + plate_padding * 2), (0, 0, 0, 155))
        plate_draw = ImageDraw.Draw(plate)
        plate_draw.rounded_rectangle((0, 0, plate.width - 1, plate.height - 1), radius=plate_padding, outline=(255, 255, 255, 70), width=2)
        final_img.paste(plate, (logo_x - plate_padding, logo_y - plate_padding), plate)
        final_img.paste(logo, (logo_x, logo_y), logo)

    return final_img


def save_wallpaper(img, target_width, target_height, gradient_style='soft', logo_url='', art_scale=100):
    collection_logo = load_logo_image(logo_url)
    tmp_folder = os.path.join(app.root_path, 'tmp')
    os.makedirs(tmp_folder, exist_ok=True)
    rgb_image = img.convert('RGB')
    rgb_image.save(os.path.join(tmp_folder, 'target_img.png'))
    final_img = create_wallpaper(rgb_image, target_width, target_height, gradient_style, collection_logo, art_scale)
    final_img.save(os.path.join(tmp_folder, 'image_converted.png'))


@app.route('/', methods=["POST", "GET"])
def main_page():
    if request.method == "GET":
        tmp_folder = 'tmp'
        try:
            for filename in os.listdir(tmp_folder):
                file_path = os.path.join(tmp_folder, filename)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
        except Exception as e:
            print(e)
        return render_home()
    else:
        img_address = request.form['pname']
        device_type = request.form.get('device', 'iphone_x')
        custom_width = request.form.get('custom_width')
        custom_height = request.form.get('custom_height')
        gradient_style = request.form.get('gradient_style', 'soft')
        logo_url = request.form.get('logo_url', '').strip()
        art_scale = get_art_scale(request.form.get('art_scale', 100))

        target_width, target_height = get_device_dimensions(device_type, custom_width, custom_height)

        if target_width is None or target_height is None:
            flash('Invalid device dimensions. Please check your custom size values.', 'error')
            return render_home()

        try:
            response = requests.get(img_address, timeout=15)
            html_content = response.text
            soup = BeautifulSoup(html_content, 'html.parser')

            if response.status_code == 200:
                img_tag = soup.find("meta", property="og:image")
                title_tag = soup.find("meta", property="og:title")

                if img_tag and title_tag:
                    img_src = img_tag["content"]
                    title = title_tag["content"]

                    img_response = requests.get(img_src, timeout=15)
                    if img_response.status_code != 200:
                        raise ValueError('The NFT image could not be downloaded.')
                    img = Image.open(BytesIO(img_response.content))

                    save_wallpaper(img, target_width, target_height, gradient_style, logo_url, art_scale)

                    session['title'] = title
                    session['img_src'] = img_src
                    session['source_url'] = img_address
                    session['device_type'] = device_type
                    session['dimensions'] = f"{target_width} × {target_height}"
                    session['gradient_style'] = gradient_style
                    session['logo_url'] = logo_url
                    session['art_scale'] = art_scale

                    return redirect('/create')
                else:
                    flash('Unable to retrieve NFT details. Please check the link and try again.', 'error')
                    return render_home()
            else:
                flash('Unable to retrieve NFT details. Please check the link and try again.', 'error')
                return render_home()

        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'error')
            return render_home()


@app.route('/explore')
def explore_page():
    query = request.args.get('q', '').strip()
    live_collection = request.args.get('collection_slug', '').strip()
    next_token = request.args.get('next', '').strip()

    live_results = []
    live_next = None
    live_error = None
    live_collection_logo = ''
    live_collection_name = ''
    if not OPENSEA_API_KEY:
        live_error = 'Add OPENSEA_API_KEY to .env to enable live OpenSea discovery.'
    elif live_collection:
        collection = get_opensea_collection(live_collection)
        if collection:
            live_collection_logo = collection['image'] if not collection['image'].startswith('/static/') else ''
            live_collection_name = collection['name']
        live_results, live_next = list_opensea_collection_nfts(live_collection, next_token)
    elif query:
        live_results, live_next = search_opensea(query, next_token)
    else:
        live_results, live_next = list_opensea_collections(next_token)

    if live_results is None:
        live_error = 'OpenSea is unavailable right now. Try again in a moment.'
        live_results = []

    return render_template(
        'explore.html',
        **catalog_context(),
        query=query,
        live_results=live_results,
        live_next=live_next,
        live_collection=live_collection,
        live_collection_logo=live_collection_logo,
        live_collection_name=live_collection_name,
        live_error=live_error,
        opensea_configured=bool(OPENSEA_API_KEY),
    )


@app.route('/marketplace/generate', methods=['POST'])
def marketplace_generate():
    image_url = request.form.get('image_url', '').strip()
    title = request.form.get('title', 'OpenSea NFT').strip()[:200]
    source_url = request.form.get('source_url', '').strip()
    device_type = request.form.get('device', 'iphone_x')
    custom_width = request.form.get('custom_width')
    custom_height = request.form.get('custom_height')
    gradient_style = request.form.get('gradient_style', 'soft')
    logo_url = request.form.get('logo_url', '').strip()
    art_scale = get_art_scale(request.form.get('art_scale', 100))
    target_width, target_height = get_device_dimensions(device_type, custom_width, custom_height)

    if not image_url.startswith(('http://', 'https://')):
        flash('This marketplace item does not have a usable image URL.', 'error')
        return redirect(url_for('explore_page'))
    if target_width is None or target_height is None:
        flash('Invalid device dimensions. Please check your custom size values.', 'error')
        return redirect(url_for('explore_page'))

    try:
        image_response = requests.get(image_url, timeout=15)
        if image_response.status_code != 200:
            raise ValueError('The marketplace image could not be downloaded.')

        os.makedirs(os.path.join(app.root_path, 'tmp'), exist_ok=True)
        with Image.open(BytesIO(image_response.content)) as source_image:
            save_wallpaper(source_image, target_width, target_height, gradient_style, logo_url, art_scale)

        session['title'] = title or 'OpenSea NFT'
        session['img_src'] = image_url
        session['source_url'] = source_url or image_url
        session['device_type'] = device_type
        session['dimensions'] = f"{target_width} × {target_height}"
        session['gradient_style'] = gradient_style
        session['logo_url'] = logo_url
        session['art_scale'] = art_scale
        return redirect(url_for('create_page'))
    except Exception as error:
        flash(f'Unable to prepare this marketplace NFT: {error}', 'error')
        return redirect(url_for('explore_page'))


@app.route('/image/<filename>')
def get_image(filename):
    return send_from_directory('tmp', filename)


@app.route('/create', methods=["POST", "GET"])
def create_page():
    if request.method == "GET":
        if 'title' not in session or 'img_src' not in session:
            flash('Session expired. Please generate a new wallpaper.', 'error')
            return redirect(url_for('main_page'))

        return render_template('create.html',
                               img_src=session['img_src'],
                               source_url=session.get('source_url', session['img_src']),
                               art_title=session['title'],
                               device_type=session.get('device_type', 'Unknown'),
                               dimensions=session.get('dimensions', 'Unknown'),
                               gradient_style=session.get('gradient_style', 'soft'),
                               logo_url=session.get('logo_url', ''),
                               art_scale=session.get('art_scale', 100),
                               time_now=datetime.now().timestamp())


@app.route('/download')
def download_page():
    path = "tmp/image_converted.png"
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
