import os
import logging
import requests
import pandas as pd
from dotenv import load_dotenv

# Initialize logging
logger = logging.getLogger(__name__)
load_dotenv()

class StravaClient:
    def __init__(self):
        self.client_id = os.getenv("STRAVA_CLIENT_ID")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET")
        self.refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")
        self.auth_url = "https://www.strava.com/oauth/token"
        self.base_url = "https://www.strava.com/api/v3"

    def get_access_token(self):
        """Refresh and retrieve a valid access token."""
        payload = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token'
        }
        try:
            response = requests.post(self.auth_url, data=payload)
            response.raise_for_status()
            return response.json().get('access_token')
        except Exception as e:
            logger.error(f"[STRAVA] Failed to refresh token: {e}")
            return None

    def get_activity_data(self, activity_id: str):
        """
        Fetch activity streams (HR, Cadence, Velocity) and convert to CSV string.
        Returns: (activity_name, csv_data_string)
        """
        token = self.get_access_token()
        if not token:
            return None, None

        headers = {'Authorization': f'Bearer {token}'}
        
        # 1. Get Activity Details (Name, Type)
        try:
            act_url = f"{self.base_url}/activities/{activity_id}"
            act_res = requests.get(act_url, headers=headers)
            if act_res.status_code != 200:
                logger.error(f"[STRAVA] Error fetching activity: {act_res.text}")
                return None, None
            
            act_data = act_res.json()
            activity_name = act_data.get('name', 'Unknown Run')
            
            # Check type (Run, VirtualRun, etc.)
            if act_data.get('type') not in ['Run', 'VirtualRun', 'TrailRun', 'Treadmill']:
                logger.info(f"[STRAVA] Activity {activity_id} is not a run. Skipping.")
                return None, None

            # 2. Get Streams
            streams_url = f"{act_url}/streams?keys=time,heartrate,velocity_smooth,cadence,grade_smooth&key_by_type=true"
            streams_res = requests.get(streams_url, headers=headers).json()

            # 3. Process with Pandas (Logic ported from old script)
            data = {
                'Time_sec': streams_res.get('time', {}).get('data', []),
                'HR_bpm': streams_res.get('heartrate', {}).get('data', []),
                'Velocity_m_s': streams_res.get('velocity_smooth', {}).get('data', []),
                'Cadence_spm': streams_res.get('cadence', {}).get('data', []),
                'Grade_pct': streams_res.get('grade_smooth', {}).get('data', [])
            }
            
            # Create DataFrame
            df = pd.DataFrame(dict([(k, pd.Series(v)) for k, v in data.items()]))
            
            # Clean data (Drop rows with missing critical data)
            df.dropna(subset=['HR_bpm', 'Velocity_m_s'], inplace=True)
            
            # Convert to CSV string for Gemini
            csv_data = df.to_csv(index=False)
            logger.info(f"[STRAVA] Successfully processed CSV data for {activity_id}")
            
            return activity_name, csv_data

        except Exception as e:
            logger.error(f"[STRAVA] Error processing activity data: {e}")
            return None, None

    def update_activity_description(self, activity_id: str, description: str):
        """Update the description of a Strava activity."""
        token = self.get_access_token()
        if not token: return False

        url = f"{self.base_url}/activities/{activity_id}"
        headers = {'Authorization': f'Bearer {token}'}
        payload = {'description': description}

        try:
            response = requests.put(url, headers=headers, json=payload)
            if response.status_code == 200:
                logger.info(f"[STRAVA] Description updated for {activity_id}")
                return True
            else:
                logger.error(f"[STRAVA] Failed update: {response.text}")
                return False
        except Exception as e:
            logger.error(f"[STRAVA] Error updating description: {e}")
            return False