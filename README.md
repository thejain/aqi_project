# 🌬️ AQI Intelligence Dashboard — India

A professional Air Quality Index prediction web application using Machine Learning (Random Forest), live OpenWeather API data, and India CPCB-standard AQI computation.

---

## 📁 Project Structure

```
aqi_project/
├── app.py              ← Flask backend (all API routes)
├── train_model.py      ← Train Random Forest model
├── requirements.txt    ← Python dependencies
├── model.pkl           ← Trained model (auto-generated)
├── data/
│   └── mydataset.csv   ← India AQI historical dataset (2015–2024)
├── templates/
│   └── index.html      ← Frontend HTML
└── static/
    ├── style.css        ← Dashboard CSS (dark glassmorphism theme)
    └── script.js        ← All frontend JavaScript + Chart.js
```

---

## ⚙️ Setup & Run (Step by Step)

### Step 1 — Clone / extract the project folder

Place the entire `aqi_project/` folder somewhere on your machine.

### Step 2 — Create a Python virtual environment

```bash
cd aqi_project
python -m venv venv
```

Activate it:
- **Windows:** `venv\Scripts\activate`
- **Mac/Linux:** `source venv/bin/activate`

### Step 3 — Configure local environment

Copy the example `.env.example` file to `.env` and set your OpenWeather API key:

```bash
copy .env.example .env
```

Then edit `.env` and replace `your_api_key_here` with your OpenWeather API key.

> If you do not have an API key yet, the app still runs locally and falls back to historical CSV values for AQI/weather data.

### Step 4 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 5 — Train the ML model *(one-time step)*

If `model.pkl` already exists in the project root, you can skip this step.

```bash
python train_model.py
```

This will:
- Load `data/mydataset.csv`
- Recompute AQI using the **India CPCB standard formula** from PM2.5, PM10, NO₂, SO₂, CO, O₃
- Train a **Random Forest Regressor** (300 trees, depth 25)
- Save `model.pkl` with ~98%+ accuracy (R² ≈ 0.98, MAE ≈ 7 AQI units)

Expected output:
```
Loading dataset...
Train: 16430, Test: 1830
Test R2: 0.9819, MAE: 7.11, Within±50: 98.9%
Model saved -> model.pkl
Done! Accuracy: 98.9%
```

### Step 5 — Start the Flask server

```bash
python app.py
```

### Step 6 — Open in browser

```
http://127.0.0.1:5000
```

---

## 🚀 Deployment

### Heroku Deployment

1. **Install Heroku CLI** and login:
   ```bash
   heroku login
   ```

2. **Create a Heroku app**:
   ```bash
   heroku create your-app-name
   ```

3. **Set environment variable for OpenWeather API key**:
   ```bash
   heroku config:set OPENWEATHER_API_KEY=your_api_key_here
   ```

4. **Deploy**:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git push heroku main
   ```

5. **Open the app**:
   ```bash
   heroku open
   ```

### Other Platforms

- **AWS Elastic Beanstalk**: Use `eb init`, `eb create`, `eb deploy`
- **Google App Engine**: Create `app.yaml` and deploy with `gcloud app deploy`
- **Docker**: Build and run the containerized app

#### Docker Deployment

1. **Build the Docker image**:
   ```bash
   docker build -t aqi-dashboard .
   ```

2. **Run the container** (set your API key):
   ```bash
   docker run -p 5000:5000 -e OPENWEATHER_API_KEY=your_api_key_here aqi-dashboard
   ```

3. **Or use Docker Compose** (recommended for development):
   ```bash
   # Set your API key in .env file or export it
   copy .env.example .env
   # Then edit .env and add your OpenWeather API key.
   docker-compose up --build
   ```

4. **Open in browser**:
   ```
   http://localhost:5000
   ```

For production, ensure the `OPENWEATHER_API_KEY` environment variable is set.

---

## 🌐 API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/cities` | List of 5 Indian cities + model accuracy |
| `GET /api/past_aqi?city=Delhi` | Last 3 days AQI from CSV |
| `GET /api/live_aqi?city=Delhi` | Live AQI via OpenWeather (CPCB formula) |
| `GET /api/weather?city=Delhi` | Live weather (temp, humidity, wind, etc.) |
| `GET /api/forecast?city=Delhi` | Next 2-day AQI prediction using RF model |
| `GET /api/history_chart?city=Delhi&days=30` | 30-day AQI + pollutant trend data |
| `GET /api/pollutant_comparison?city=Delhi` | 30-day average pollutant levels |
| `GET /api/zone_cities` | Cities grouped by AQI zone (for gauge hover) |

---

## 🤖 ML Model Details

| Parameter | Value |
|---|---|
| Algorithm | Random Forest Regressor |
| Trees | 300 (`n_estimators`) |
| Max Depth | 25 |
| Max Features | sqrt |
| Target | AQI (CPCB-recomputed) |
| R² Score | ~0.98 |
| MAE | ~7 AQI units |
| Within ±50 AQI | ~99% |

**Features used:**
- All pollutants: PM2.5, PM10, NO, NO₂, NOₓ, NH₃, CO, SO₂, O₃, Benzene, Toluene, Xylene
- Derived: PM ratio, Oxidant Index
- Temporal: month, day, day-of-week, year, quarter, season
- City encoding (Label Encoder)
- Historical patterns: monthly average AQI, city mean/std
- Rolling averages: 7/14/30-day AQI and PM2.5 rolling means

---

## 🎨 Dashboard Features

- **Live AQI Speedometer** — animated gauge with needle + color zones
- **Zone Hover** — hover over gauge color zones to see which cities fall in that category
- **Past 3 Days** — AQI cards from historical CSV data
- **Weather Panel** — temp, humidity, wind, pressure, visibility (OpenWeather)
- **2-Day Forecast** — tomorrow + day-after AQI via Random Forest
- **30-Day Trend Chart** — switchable AQI / PM2.5 / PM10 tabs
- **Pollutant Bar Chart** — 30-day average breakdown
- **AQI Scale Legend** — India CPCB 6-level reference
- **Pollutant Readings** — animated progress bars for all 6 key pollutants
- **Health Advice** — auto-generated based on current AQI level

---

## ⚠️ Notes

- **Internet required** for live AQI and weather data. If offline, the app falls back gracefully to historical CSV data.
- The OpenWeather free tier supports up to 60 calls/minute.
- The `train_model.py` must be run **at least once** before starting `app.py`.
