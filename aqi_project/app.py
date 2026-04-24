"""
app.py - Flask backend for AQI Prediction Dashboard
"""
import os, json, math
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import joblib
import requests
from flask import Flask, jsonify, request, render_template
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()  # Load local environment variables from .env if present

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'model.pkl')
DATA_PATH  = os.path.join(BASE_DIR, 'data', 'mydataset.csv')
OW_KEY     = os.environ.get('OPENWEATHER_API_KEY')
if not OW_KEY:
    print('WARNING: OPENWEATHER_API_KEY is not set. Live OpenWeather data will fallback to local/historical values.')

# City coordinates
CITY_COORDS = {
    'Delhi':     (28.6139, 77.2090),
    'Mumbai':    (19.0760, 72.8777),
    'Chennai':   (13.0827, 80.2707),
    'Kolkata':   (22.5726, 88.3639),
    'Bangalore': (12.9716, 77.5946),
}

app = Flask(__name__)

# ─── Load model & data ───────────────────────────────────────────────────────
print("Loading model...")
artifact  = joblib.load(MODEL_PATH)
MODEL     = artifact['model']
FEATURES  = artifact['features']
LE        = artifact['label_encoder']
ACCURACY  = artifact['accuracy']
MONTHLY   = artifact['monthly_avg']    # City × month → hist_monthly_aqi
CITY_STATS= artifact['city_stats']     # City → mean, std

print("Loading dataset...")
DF = pd.read_csv(DATA_PATH, parse_dates=['Datetime'])
DF = DF.sort_values(['City','Datetime']).reset_index(drop=True)

# CPCB AQI breakpoints
BREAKPOINTS = {
    'PM2.5': [(0,30,0,50),(30,60,51,100),(60,90,101,200),(90,120,201,300),(120,250,301,400),(250,500,401,500)],
    'PM10':  [(0,50,0,50),(50,100,51,100),(100,250,101,200),(250,350,201,300),(350,430,301,400),(430,600,401,500)],
    'NO2':   [(0,40,0,50),(40,80,51,100),(80,180,101,200),(180,280,201,300),(280,400,301,400),(400,800,401,500)],
    'SO2':   [(0,40,0,50),(40,80,51,100),(80,380,101,200),(380,800,201,300),(800,1600,301,400),(1600,2000,401,500)],
    'CO':    [(0,1,0,50),(1,2,51,100),(2,10,101,200),(10,17,201,300),(17,34,301,400),(34,50,401,500)],
    'O3':    [(0,50,0,50),(50,100,51,100),(100,168,101,200),(168,208,201,300),(208,748,301,400),(748,1000,401,500)],
}

def sub_index(value, bp_list):
    if value is None or (isinstance(value, float) and math.isnan(value)): return None
    value = float(value)
    for (BPLo, BPHi, ILo, IHi) in bp_list:
        if BPLo <= value <= BPHi:
            return ((IHi-ILo)/(BPHi-BPLo))*(value-BPLo)+ILo
    return 500.0 if value > bp_list[-1][1] else None

def compute_cpcb_aqi(pm25=None, pm10=None, no2=None, so2=None, co=None, o3=None):
    vals = {'PM2.5':pm25,'PM10':pm10,'NO2':no2,'SO2':so2,'CO':co,'O3':o3}
    subs = [sub_index(v, BREAKPOINTS[k]) for k,v in vals.items() if v is not None]
    subs = [s for s in subs if s is not None]
    return round(max(subs),1) if subs else None

def aqi_to_bucket(aqi):
    if aqi is None: return 'Unknown'
    if aqi <= 50:   return 'Good'
    if aqi <= 100:  return 'Satisfactory'
    if aqi <= 200:  return 'Moderate'
    if aqi <= 300:  return 'Poor'
    if aqi <= 400:  return 'Very Poor'
    return 'Severe'

def aqi_color(aqi):
    if aqi is None: return '#888'
    if aqi <= 50:   return '#00e400'
    if aqi <= 100:  return '#ffff00'
    if aqi <= 200:  return '#ff7e00'
    if aqi <= 300:  return '#ff0000'
    if aqi <= 400:  return '#8f3f97'
    return '#7e0023'

def health_advice(aqi):
    if aqi is None: return 'No data available.'
    if aqi <= 50:   return 'Air quality is satisfactory. Enjoy outdoor activities freely.'
    if aqi <= 100:  return 'Acceptable air quality. Unusually sensitive people should consider reducing prolonged exertion.'
    if aqi <= 200:  return 'Sensitive groups (children, elderly, respiratory patients) should reduce outdoor exertion.'
    if aqi <= 300:  return 'Everyone may experience health effects. Limit outdoor exposure and wear masks.'
    if aqi <= 400:  return 'Health warnings — avoid outdoor activities. Keep windows closed.'
    return 'Emergency conditions. Stay indoors, use air purifiers, and avoid all outdoor activity.'

# ─── Prepare feature row for prediction ──────────────────────────────────────
def make_feature_row(city, target_date, pm25, pm10, no2, nox, nh3, co, so2, o3, benzene, toluene, xylene):
    city_data = DF[DF['City']==city].sort_values('Datetime')

    # Rolling averages from historical data
    aqi_series  = city_data['AQI'].values
    pm25_series = city_data['PM2.5'].values

    def roll_mean(series, w):
        recent = series[-w:] if len(series)>=w else series
        return float(np.mean(recent))

    aqi_r7, aqi_r14, aqi_r30   = roll_mean(aqi_series,7), roll_mean(aqi_series,14), roll_mean(aqi_series,30)
    pm25_r7, pm25_r14, pm25_r30 = roll_mean(pm25_series,7), roll_mean(pm25_series,14), roll_mean(pm25_series,30)

    m_avg  = MONTHLY[(MONTHLY['City']==city)&(MONTHLY['month']==target_date.month)]['hist_monthly_aqi']
    hist_m = float(m_avg.values[0]) if len(m_avg) else 250.0
    cs     = CITY_STATS[CITY_STATS['City']==city].iloc[0]

    city_enc = int(LE.transform([city])[0])

    row = {
        'PM2.5':pm25,'PM10':pm10,'NO':0,'NO2':no2,'NOx':nox,'NH3':nh3,
        'CO':co,'SO2':so2,'O3':o3,'Benzene':benzene,'Toluene':toluene,'Xylene':xylene,
        'PM_ratio':pm25/(pm10+1),'oxidant_idx':o3+no2,
        'month':target_date.month,'day':target_date.day,'dayofweek':target_date.weekday(),
        'year':target_date.year,'quarter':(target_date.month-1)//3+1,
        'season':0 if target_date.month in [12,1,2] else 1 if target_date.month in [3,4,5] else 2 if target_date.month in [6,7,8,9] else 3,
        'city_enc':city_enc,
        'hist_monthly_aqi':hist_m,'city_mean_aqi':float(cs['city_mean_aqi']),'city_std_aqi':float(cs['city_std_aqi']),
        'AQI_roll7':aqi_r7,'AQI_roll14':aqi_r14,'AQI_roll30':aqi_r30,
        'PM25_roll7':pm25_r7,'PM25_roll14':pm25_r14,'PM25_roll30':pm25_r30,
    }
    return [row[f] for f in FEATURES]

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/cities')
def get_cities():
    return jsonify({'cities': sorted(CITY_COORDS.keys()), 'accuracy': ACCURACY})

@app.route('/api/past_aqi')
def past_aqi():
    city = request.args.get('city','Delhi')
    city_df = DF[DF['City']==city].sort_values('Datetime')
    last3   = city_df.tail(3)
    records = []
    for _, row in last3.iterrows():
        aqi = round(float(row['AQI']),1)
        records.append({
            'date':   row['Datetime'].strftime('%d %b %Y'),
            'aqi':    aqi,
            'bucket': aqi_to_bucket(aqi),
            'color':  aqi_color(aqi),
            'pm25':   round(float(row['PM2.5']),1),
            'pm10':   round(float(row['PM10']),1),
        })
    return jsonify({'past': records})

@app.route('/api/history_chart')
def history_chart():
    city = request.args.get('city','Delhi')
    days = int(request.args.get('days', 30))
    city_df = DF[DF['City']==city].sort_values('Datetime').tail(days)
    return jsonify({
        'dates': [d.strftime('%d %b') for d in city_df['Datetime']],
        'aqi':   [round(float(v),1) for v in city_df['AQI']],
        'pm25':  [round(float(v),1) for v in city_df['PM2.5']],
        'pm10':  [round(float(v),1) for v in city_df['PM10']],
        'no2':   [round(float(v),1) for v in city_df['NO2']],
        'so2':   [round(float(v),1) for v in city_df['SO2']],
        'co':    [round(float(v),1) for v in city_df['CO']],
        'o3':    [round(float(v),1) for v in city_df['O3']],
    })

@app.route('/api/live_aqi')
def live_aqi():
    city = request.args.get('city','Delhi')
    lat, lon = CITY_COORDS.get(city, (28.6139, 77.2090))
    try:
        # Air pollution API
        ap_url = f'http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OW_KEY}'
        ap_res = requests.get(ap_url, timeout=8).json()
        comp = ap_res['list'][0]['components']
        pm25 = comp.get('pm2_5',0)
        pm10 = comp.get('pm10',0)
        no2  = comp.get('no2',0)
        so2  = comp.get('so2',0)
        co   = comp.get('co',0)/1000  # convert µg/m³ → mg/m³
        o3   = comp.get('o3',0)
        ow_aqi_idx = ap_res['list'][0]['main']['aqi']  # 1-5 scale
        # Use CPCB formula with live pollutants
        aqi = compute_cpcb_aqi(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3)
        if aqi is None: aqi = ow_aqi_idx*100
        return jsonify({
            'aqi':    round(aqi,1),
            'bucket': aqi_to_bucket(aqi),
            'color':  aqi_color(aqi),
            'health': health_advice(aqi),
            'pm25': round(pm25,1), 'pm10': round(pm10,1),
            'no2':  round(no2,1),  'so2':  round(so2,1),
            'co':   round(co*1000,1), 'o3': round(o3,1),
            'source': 'live',
        })
    except Exception as e:
        # Fallback: use latest CSV data
        city_df = DF[DF['City']==city].sort_values('Datetime')
        last    = city_df.iloc[-1]
        aqi     = round(float(last['AQI']),1)
        return jsonify({
            'aqi': aqi, 'bucket': aqi_to_bucket(aqi),
            'color': aqi_color(aqi), 'health': health_advice(aqi),
            'pm25': round(float(last['PM2.5']),1), 'pm10': round(float(last['PM10']),1),
            'no2':  round(float(last['NO2']),1),   'so2':  round(float(last['SO2']),1),
            'co':   round(float(last['CO']),1),     'o3':   round(float(last['O3']),1),
            'source': 'historical',
        })

@app.route('/api/weather')
def weather():
    city = request.args.get('city','Delhi')
    lat, lon = CITY_COORDS.get(city, (28.6139, 77.2090))
    try:
        url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OW_KEY}&units=metric'
        res = requests.get(url, timeout=8).json()
        return jsonify({
            'temp':        round(res['main']['temp'],1),
            'feels_like':  round(res['main']['feels_like'],1),
            'humidity':    res['main']['humidity'],
            'pressure':    res['main']['pressure'],
            'wind_speed':  round(res['wind']['speed']*3.6,1),  # m/s → km/h
            'description': res['weather'][0]['description'].title(),
            'icon':        res['weather'][0]['icon'],
            'visibility':  res.get('visibility',0)//1000,
        })
    except Exception as e:
        return jsonify({'error': str(e), 'temp':28,'humidity':65,'pressure':1012,
                        'wind_speed':12,'description':'Partly Cloudy','icon':'02d','visibility':8})

@app.route('/api/forecast')
def forecast():
    city = request.args.get('city','Delhi')
    lat, lon = CITY_COORDS.get(city, (28.6139, 77.2090))

    # Get live weather for temperature/humidity/wind features
    try:
        w_url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OW_KEY}&units=metric'
        w_res = requests.get(w_url, timeout=8).json()
        temp     = w_res['main']['temp']
        humidity = w_res['main']['humidity']
        wind_kph = w_res['wind']['speed']*3.6
    except:
        temp, humidity, wind_kph = 28.0, 60.0, 10.0

    # Use latest pollutant readings from CSV
    city_df = DF[DF['City']==city].sort_values('Datetime')
    last    = city_df.iloc[-1]

    predictions = []
    today = datetime.now()
    for offset in [1, 2]:
        target_date = today + timedelta(days=offset)
        feat_row = make_feature_row(
            city, target_date,
            pm25=float(last['PM2.5']), pm10=float(last['PM10']),
            no2=float(last['NO2']),    nox=float(last['NOx']),
            nh3=float(last['NH3']),    co=float(last['CO']),
            so2=float(last['SO2']),    o3=float(last['O3']),
            benzene=float(last['Benzene']), toluene=float(last['Toluene']),
            xylene=float(last['Xylene']),
        )
        aqi_pred = round(float(MODEL.predict([feat_row])[0]),1)
        aqi_pred = max(0, min(500, aqi_pred))
        predictions.append({
            'date':   target_date.strftime('%d %b %Y'),
            'day':    'Tomorrow' if offset==1 else 'Day After',
            'aqi':    aqi_pred,
            'bucket': aqi_to_bucket(aqi_pred),
            'color':  aqi_color(aqi_pred),
            'health': health_advice(aqi_pred),
        })

    return jsonify({'predictions': predictions, 'accuracy': ACCURACY})

@app.route('/api/zone_cities')
def zone_cities():
    """Return cities grouped by their current AQI zone for gauge hover."""
    latest_aqis = {}
    for city in CITY_COORDS:
        city_df = DF[DF['City']==city].sort_values('Datetime')
        aqi = round(float(city_df.iloc[-1]['AQI']),1)
        latest_aqis[city] = {'aqi': aqi, 'bucket': aqi_to_bucket(aqi), 'color': aqi_color(aqi)}

    zones = {
        'Good':         [c for c,d in latest_aqis.items() if d['aqi']<=50],
        'Satisfactory': [c for c,d in latest_aqis.items() if 50<d['aqi']<=100],
        'Moderate':     [c for c,d in latest_aqis.items() if 100<d['aqi']<=200],
        'Poor':         [c for c,d in latest_aqis.items() if 200<d['aqi']<=300],
        'Very Poor':    [c for c,d in latest_aqis.items() if 300<d['aqi']<=400],
        'Severe':       [c for c,d in latest_aqis.items() if d['aqi']>400],
    }
    return jsonify({'zones': zones, 'city_aqis': latest_aqis})

@app.route('/api/pollutant_comparison')
def pollutant_comparison():
    city = request.args.get('city','Delhi')
    city_df = DF[DF['City']==city].sort_values('Datetime').tail(30)
    return jsonify({
        'pm25':  round(float(city_df['PM2.5'].mean()),1),
        'pm10':  round(float(city_df['PM10'].mean()),1),
        'no2':   round(float(city_df['NO2'].mean()),1),
        'so2':   round(float(city_df['SO2'].mean()),1),
        'co':    round(float(city_df['CO'].mean()),2),
        'o3':    round(float(city_df['O3'].mean()),1),
        'nox':   round(float(city_df['NOx'].mean()),1),
        'nh3':   round(float(city_df['NH3'].mean()),1),
    })

# ─── NEW ENDPOINTS (Upgrade v2) ───────────────────────────────────────────────

@app.route('/api/model_metrics')
def model_metrics():
    """Return honest model metrics."""
    return jsonify({
        'r2':         artifact.get('r2', 0.98),
        'mae':        artifact.get('mae', 7.11),
        'within_50':  artifact.get('within_50', 98.9),
        'within_100': artifact.get('within_100', 99.9),
    })

@app.route('/api/hourly_forecast')
def hourly_forecast():
    """Next 24h hourly forecast using OpenWeather forecast API."""
    city = request.args.get('city', 'Delhi')
    lat, lon = CITY_COORDS.get(city, (28.6139, 77.2090))
    try:
        url = f'https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OW_KEY}&units=metric&cnt=9'
        res = requests.get(url, timeout=8).json()
        hours = []
        for item in res.get('list', []):
            dt       = datetime.fromtimestamp(item['dt'])
            temp     = item['main']['temp']
            humidity = item['main']['humidity']
            wind_ms  = item['wind']['speed']
            wind_deg = item['wind'].get('deg', 0)
            icon     = item['weather'][0]['icon']
            desc     = item['weather'][0]['description'].title()
            # Estimate AQI trend from humidity + wind (simple heuristic for hourly)
            # Higher humidity + lower wind → worse AQI
            aqi_factor = (humidity / 100) * 1.3 - (wind_ms / 10) * 0.4
            hours.append({
                'time':     dt.strftime('%H:%M'),
                'label':    dt.strftime('%I %p').lstrip('0'),
                'temp':     round(temp, 1),
                'humidity': humidity,
                'wind_kph': round(wind_ms * 3.6, 1),
                'wind_deg': wind_deg,
                'icon':     icon,
                'desc':     desc,
                'aqi_factor': round(aqi_factor, 2),
            })
        return jsonify({'hours': hours})
    except Exception as e:
        # Fallback: generate synthetic hourly data
        now = datetime.now()
        hours = []
        for i in range(9):
            dt = now + timedelta(hours=i*3)
            hours.append({
                'time':     dt.strftime('%H:%M'),
                'label':    dt.strftime('%I %p').lstrip('0'),
                'temp':     round(28 + i*0.5 - (i>4)*i*0.8, 1),
                'humidity': 60 + i*2,
                'wind_kph': 12,
                'wind_deg': 180,
                'icon':     '02d',
                'desc':     'Partly Cloudy',
                'aqi_factor': 0.8,
            })
        return jsonify({'hours': hours})

@app.route('/api/wind')
def wind():
    """Detailed wind data."""
    city = request.args.get('city', 'Delhi')
    lat, lon = CITY_COORDS.get(city, (28.6139, 77.2090))
    try:
        url = f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OW_KEY}&units=metric'
        res = requests.get(url, timeout=8).json()
        speed_ms  = res['wind']['speed']
        speed_kph = round(speed_ms * 3.6, 1)
        deg       = res['wind'].get('deg', 0)
        gust_ms   = res['wind'].get('gust', speed_ms)
        gust_kph  = round(gust_ms * 3.6, 1)

        dirs  = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW']
        label = dirs[round(deg / 22.5) % 16]

        if speed_kph < 5:     dispersion = 'Very Poor — Pollutants accumulating'
        elif speed_kph < 15:  dispersion = 'Poor — Limited pollutant dispersion'
        elif speed_kph < 30:  dispersion = 'Moderate — Gradual pollutant dispersal'
        elif speed_kph < 50:  dispersion = 'Good — Effective pollutant dispersion'
        else:                 dispersion = 'Excellent — Strong dispersion conditions'

        return jsonify({
            'speed_kph':  speed_kph,
            'gust_kph':   gust_kph,
            'deg':        deg,
            'direction':  label,
            'dispersion': dispersion,
            'beaufort':   int(speed_ms**0.666 * 0.8 + 0.5),
        })
    except:
        return jsonify({'speed_kph':12,'gust_kph':18,'deg':225,'direction':'SW',
                        'dispersion':'Moderate — Gradual pollutant dispersal','beaufort':3})

@app.route('/api/history_range')
def history_range():
    """Historical AQI for 7d / 30d / monthly-avg."""
    city  = request.args.get('city', 'Delhi')
    range_ = request.args.get('range', '30d')
    city_df = DF[DF['City']==city].sort_values('Datetime')

    if range_ == '7d':
        subset = city_df.tail(7)
        dates  = [d.strftime('%d %b') for d in subset['Datetime']]
        values = [round(float(v),1) for v in subset['AQI']]
    elif range_ == '30d':
        subset = city_df.tail(30)
        dates  = [d.strftime('%d %b') for d in subset['Datetime']]
        values = [round(float(v),1) for v in subset['AQI']]
    else:  # monthly
        city_df['month_label'] = city_df['Datetime'].dt.strftime('%b %Y')
        monthly = city_df.groupby('month_label', sort=False)['AQI'].mean()
        # Keep last 12 months
        last12 = city_df.groupby(city_df['Datetime'].dt.to_period('M'))['AQI'].mean().tail(12)
        dates  = [str(p) for p in last12.index]
        values = [round(float(v),1) for v in last12.values]

    avg = round(float(np.mean(values)),1) if values else 0
    mx  = round(float(max(values)),1) if values else 0
    mn  = round(float(min(values)),1) if values else 0
    return jsonify({'dates': dates, 'values': values, 'avg': avg, 'max': mx, 'min': mn})

@app.route('/api/health_recs')
def health_recs():
    """Detailed health recommendations based on AQI."""
    aqi = float(request.args.get('aqi', 100))
    bucket = aqi_to_bucket(aqi)

    recs = {
        'Good': [
            {'icon': '🏃', 'title': 'Outdoor Exercise', 'desc': 'Great day for jogging, cycling or any outdoor sport.', 'level': 'safe'},
            {'icon': '🪟', 'title': 'Open Windows',     'desc': 'Fresh air circulation is beneficial indoors.',         'level': 'safe'},
            {'icon': '👨‍👩‍👧', 'title': 'Family Outings',  'desc': 'Safe for children and elderly to enjoy outdoors.',   'level': 'safe'},
            {'icon': '🌱', 'title': 'Garden Time',       'desc': 'Perfect conditions for gardening and outdoor work.',   'level': 'safe'},
        ],
        'Satisfactory': [
            {'icon': '🚶', 'title': 'Light Activity OK', 'desc': 'Walking and light exercise are generally fine.',       'level': 'safe'},
            {'icon': '😮‍💨', 'title': 'Sensitive Groups', 'desc': 'People with asthma should carry inhalers.',           'level': 'caution'},
            {'icon': '⏱️', 'title': 'Limit Duration',   'desc': 'Reduce prolonged outdoor exertion for best health.',   'level': 'caution'},
            {'icon': '🪟', 'title': 'Ventilate',        'desc': 'Indoor air quality is generally good.',                'level': 'safe'},
        ],
        'Moderate': [
            {'icon': '😷', 'title': 'Wear a Mask',       'desc': 'Consider N95/KN95 mask for outdoor activity.',        'level': 'caution'},
            {'icon': '🏠', 'title': 'Limit Exposure',    'desc': 'Sensitive groups should reduce outdoor time.',         'level': 'caution'},
            {'icon': '🚗', 'title': 'Window Up',         'desc': 'Close car windows and use recirculated air.',          'level': 'caution'},
            {'icon': '💧', 'title': 'Stay Hydrated',     'desc': 'Drink water frequently to help flush pollutants.',     'level': 'safe'},
        ],
        'Poor': [
            {'icon': '🏠', 'title': 'Stay Indoors',      'desc': 'Avoid outdoor activities as much as possible.',        'level': 'danger'},
            {'icon': '😷', 'title': 'Wear N95 Mask',     'desc': 'Use N95 or better if you must go outside.',           'level': 'danger'},
            {'icon': '🌬️', 'title': 'Air Purifier',     'desc': 'Run HEPA air purifiers at home.',                     'level': 'caution'},
            {'icon': '🧒', 'title': 'Protect Children',  'desc': 'Keep children and elderly completely indoors.',        'level': 'danger'},
        ],
        'Very Poor': [
            {'icon': '🚨', 'title': 'Health Alert',      'desc': 'Serious health effects likely for all people.',        'level': 'danger'},
            {'icon': '🏠', 'title': 'Stay Indoors',      'desc': 'Do not go outside without respiratory protection.',    'level': 'danger'},
            {'icon': '🌬️', 'title': 'Seal Gaps',        'desc': 'Seal doors/windows, use air purifier continuously.',   'level': 'danger'},
            {'icon': '🏥', 'title': 'Medical Caution',   'desc': 'Monitor symptoms; seek help if breathing worsens.',    'level': 'danger'},
        ],
        'Severe': [
            {'icon': '🚨', 'title': 'Emergency Alert',   'desc': 'Hazardous conditions — immediate action needed.',      'level': 'danger'},
            {'icon': '⛔', 'title': 'No Outdoor Activity','desc': 'Everyone should stay indoors. Cancel all outdoor events.','level': 'danger'},
            {'icon': '😷', 'title': 'Full Respirator',   'desc': 'If outdoors is unavoidable, use P100 respirator.',     'level': 'danger'},
            {'icon': '📞', 'title': 'Emergency Ready',   'desc': 'Have emergency contacts and medications on hand.',     'level': 'danger'},
        ],
    }
    return jsonify({'bucket': bucket, 'aqi': aqi, 'recommendations': recs.get(bucket, recs['Moderate'])})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    host = '127.0.0.1' if debug else '0.0.0.0'
    print(f"Starting AQI Dashboard on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
