"""
ml/demand_model.py
==================
Course Demand Model for EduPredict.

Scientific Note:
Course demand forecasting requires longitudinal course enrollment time-series data.
In the absence of historical demand records, this model reports
'insufficient_historical_data' and strictly refuses to fabricate synthetic demand predictions.
"""


class DemandModel:
    def __init__(self):
        self.model = None

    def get_status(self):
        return {
            "status": "insufficient_historical_data",
            "message": "Historical course demand / enrollment time-series data is currently unavailable and missing.",
        }

    def train(self, X, y=None):
        raise ValueError("insufficient_historical_data: Cannot train demand model without historical enrollment time-series data.")

    def predict_demand(self, features):
        raise ValueError("insufficient_historical_data: Historical course demand dataset is missing.")