"""
train_model.py - Train Random Forest AQI Prediction Model
"""
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from sklearn.preprocessing import LabelEncoder
import joblib, os

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, 'data', 'mydataset.csv')
MODEL_PATH= os.path.join(BASE_DIR, 'model.pkl')

def train():
    print("Loading dataset...")
    df = pd.read_csv(DATA_PATH)
    df['Datetime']  = pd.to_datetime(df['Datetime'])
    df['month']     = df['Datetime'].dt.month
    df['day']       = df['Datetime'].dt.day
    df['dayofweek'] = df['Datetime'].dt.dayofweek
    df['year']      = df['Datetime'].dt.year
    df['quarter']   = df['Datetime'].dt.quarter
    df['season']    = df['month'].apply(lambda m: 0 if m in [12,1,2] else 1 if m in [3,4,5] else 2 if m in [6,7,8,9] else 3)

    le = LabelEncoder()
    df['city_enc'] = le.fit_transform(df['City'])
    df = df.sort_values(['City','Datetime']).reset_index(drop=True)

    monthly_avg = df.groupby(['City','month'])['AQI'].mean().reset_index()
    monthly_avg.rename(columns={'AQI':'hist_monthly_aqi'}, inplace=True)
    df = df.merge(monthly_avg, on=['City','month'], how='left')

    city_stats = df.groupby('City')['AQI'].agg(['mean','std']).reset_index()
    city_stats.columns = ['City','city_mean_aqi','city_std_aqi']
    df = df.merge(city_stats, on='City', how='left')

    for w in [7,14,30]:
        df[f'AQI_roll{w}']  = df.groupby('City')['AQI'].transform(lambda x: x.rolling(w,min_periods=1).mean().shift(1))
        df[f'PM25_roll{w}'] = df.groupby('City')['PM2.5'].transform(lambda x: x.rolling(w,min_periods=1).mean().shift(1))

    df['PM_ratio']    = df['PM2.5']/(df['PM10']+1)
    df['oxidant_idx'] = df['O3']+df['NO2']

    FEATURES = ['PM2.5','PM10','NO','NO2','NOx','NH3','CO','SO2','O3','Benzene','Toluene','Xylene',
                'PM_ratio','oxidant_idx','month','day','dayofweek','year','quarter','season','city_enc',
                'hist_monthly_aqi','city_mean_aqi','city_std_aqi',
                'AQI_roll7','AQI_roll14','AQI_roll30','PM25_roll7','PM25_roll14','PM25_roll30']

    df_clean = df.dropna(subset=FEATURES+['AQI'])
    X, y = df_clean[FEATURES], df_clean['AQI']

    test_mask = df_clean['year']==2024
    X_train, y_train = X[~test_mask], y[~test_mask]
    X_test,  y_test  = X[test_mask],  y[test_mask]
    print(f"Train: {len(X_train)}, Test: {len(X_test)}")

    model = RandomForestRegressor(n_estimators=300, max_depth=25, min_samples_leaf=1,
                                   max_features='sqrt', n_jobs=-1, random_state=42, oob_score=True)
    model.fit(X_train, y_train)

    y_pred  = model.predict(X_test)
    test_r2  = r2_score(y_test, y_pred)
    test_mae = mean_absolute_error(y_test, y_pred)
    test_rmse= np.sqrt(mean_squared_error(y_test, y_pred))
    within_50 = np.mean(np.abs(y_pred-y_test)<=50)*100
    within_100= np.mean(np.abs(y_pred-y_test)<=100)*100

    print(f"Test R2: {test_r2:.4f}, MAE: {test_mae:.2f}, Within±50: {within_50:.1f}%")

    joblib.dump({
        'model': model, 'features': FEATURES, 'label_encoder': le,
        'accuracy': round(within_50,1), 'mae': round(test_mae,2),
        'rmse': round(test_rmse,2), 'r2': round(test_r2,4),
        'within_50': round(within_50,1), 'within_100': round(within_100,1),
        'monthly_avg': monthly_avg, 'city_stats': city_stats,
    }, MODEL_PATH)
    print(f"Model saved -> {MODEL_PATH}")
    return round(within_50,1)

if __name__=='__main__':
    acc = train()
    print(f"Done! Accuracy: {acc}%")
