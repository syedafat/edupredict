import pandas as pd
from sklearn.preprocessing import StandardScaler, LabelEncoder

class DataPreprocessor:
    @staticmethod
    def clean_and_scale_data(df):
        df = df.copy()
        # Handle missing values
        numeric_columns = df.select_dtypes(include='number').columns
        if len(numeric_columns):
            df[numeric_columns] = df[numeric_columns].fillna(
                df[numeric_columns].median()
            )
        categorical_columns = df.select_dtypes(include=['object', 'category']).columns
        if len(categorical_columns):
            df[categorical_columns] = df[categorical_columns].fillna('unknown')
        
        # Encode categorical columns if present
        label_encoders = {}
        for col in categorical_columns:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            label_encoders[col] = le
            
        # Scale numerical features
        scaler = StandardScaler()
        numeric_cols = df.select_dtypes(include='number').columns
        if len(numeric_cols):
            df[numeric_cols] = scaler.fit_transform(df[numeric_cols])
        
        return df