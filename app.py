import streamlit as st
import simpy
import random
import numpy as np
from datetime import datetime, timedelta
import pandas as pd
from dataclasses import dataclass
import plotly.express as px
import plotly.graph_objects as go

# ============================
# KONFIGURASI SIMULASI
# ============================
@dataclass
class Config:
    JUMLAH_MEJA: int = 60
    OMPRENG_PER_MEJA: int = 3
    TOTAL_OMPRENG: int = 180
    NUM_PETUGAS: int = 7
    MIN_LAUK: float = 0.5
    MAX_LAUK: float = 1.0
    MIN_ANGKUT: float = 0.33
    MAX_ANGKUT: float = 1.0
    MIN_NASI: float = 0.5
    MAX_NASI: float = 1.0
    BATCH_MIN: int = 4
    BATCH_MAX: int = 7
    START_HOUR: int = 7
    START_MINUTE: int = 0
    RANDOM_SEED: int = 42

# ============================
# MODEL SIMULASI
# ============================
class PiketKantinDES:
    def __init__(self, config: Config):
        self.config = config
        self.env = simpy.Environment()
        self.petugas = simpy.Resource(self.env, capacity=config.NUM_PETUGAS)
        self.siap_angkut = simpy.Store(self.env)
        self.siap_nasi = simpy.Store(self.env)
        self.statistics = {
            'ompreng_data': [],
            'utilization': []
        }
        self.start_time = datetime(2026, 2, 11, config.START_HOUR, config.START_MINUTE)
        self.selesai_count = 0
        random.seed(config.RANDOM_SEED)
        np.random.seed(config.RANDOM_SEED)

    def waktu_ke_jam(self, waktu_simulasi: float) -> datetime:
        return self.start_time + timedelta(minutes=waktu_simulasi)

    def proses_lauk(self, ompreng_id: int):
        with self.petugas.request() as req:
            yield req
            durasi = random.uniform(self.config.MIN_LAUK, self.config.MAX_LAUK)
            yield self.env.timeout(durasi)
            yield self.siap_angkut.put({'id': ompreng_id, 'start_time': self.env.now - durasi})

    def proses_angkut(self):
        while self.selesai_count < self.config.TOTAL_OMPRENG:
            batch_size = random.randint(self.config.BATCH_MIN, self.config.BATCH_MAX)
            items = []
            for _ in range(batch_size):
                if (self.selesai_count + len(items)) < self.config.TOTAL_OMPRENG:
                    if len(self.siap_angkut.items) > 0:
                        item = yield self.siap_angkut.get()
                        items.append(item)
                    else:
                        break
            
            if items:
                with self.petugas.request() as req:
                    yield req
                    durasi = random.uniform(self.config.MIN_ANGKUT, self.config.MAX_ANGKUT)
                    yield self.env.timeout(durasi)
                    for item in items:
                        yield self.siap_nasi.put(item)
            else:
                yield self.env.timeout(0.1)

    def proses_nasi(self):
        while self.selesai_count < self.config.TOTAL_OMPRENG:
            data = yield self.siap_nasi.get()
            with self.petugas.request() as req:
                yield req
                durasi = random.uniform(self.config.MIN_NASI, self.config.MAX_NASI)
                yield self.env.timeout(durasi)
                self.selesai_count += 1
                self.statistics['ompreng_data'].append({
                    'id': data['id'],
                    'waktu_mulai': data['start_time'],
                    'waktu_selesai': self.env.now,
                    'durasi_total': self.env.now - data['start_time'],
                    'jam_selesai': self.waktu_ke_jam(self.env.now)
                })
                self.statistics['utilization'].append({
                    'time': self.env.now,
                    'in_use': self.petugas.count
                })

    def run_simulation(self):
        for i in range(self.config.TOTAL_OMPRENG):
            self.env.process(self.proses_lauk(i))
        self.env.process(self.proses_angkut())
        self.env.process(self.proses_nasi())
        self.env.run()
        return self.analyze_results()

    def analyze_results(self):
        if not self.statistics['ompreng_data']:
            return None, None
        df = pd.DataFrame(self.statistics['ompreng_data'])
        results = {
            'total_ompreng': len(df),
            'waktu_selesai_terakhir': df['waktu_selesai'].max(),
            'jam_selesai_terakhir': self.waktu_ke_jam(df['waktu_selesai'].max()),
            'avg_durasi_proses': df['durasi_total'].mean(),
            'utilitas_rata_rata': np.mean([u['in_use'] for u in self.statistics['utilization']]) / self.config.NUM_PETUGAS * 100
        }
        return results, df

# ============================
# FUNGSI VISUALISASI
# ============================
def create_process_distribution(df):
    fig = px.histogram(df, x='durasi_total', nbins=20, title='📊 Distribusi Durasi Total')
    return fig

def create_timeline_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['waktu_selesai'], y=df.index + 1, mode='lines+markers', name='Selesai'))
    fig.update_layout(title='📈 Timeline Penyelesaian')
    return fig

# ============================
# APLIKASI STREAMLIT
# ============================
def main():
    st.set_page_config(page_title="Simulasi Piket IT Del", layout="wide")
    
    with st.sidebar:
        st.subheader("⚙️ Parameter")
        num_petugas = st.slider("Jumlah Petugas", 1, 15, 7)
        total_meja = st.number_input("Jumlah Meja", value=60)
        run_sim = st.button("🚀 Jalankan Simulasi", type="primary")

    st.title("🍱 Simulasi Sistem Piket Mahasiswa IT Del")

    if run_sim:
        config = Config(NUM_PETUGAS=num_petugas, JUMLAH_MEJA=total_meja, TOTAL_OMPRENG=total_meja * 3)
        model = PiketKantinDES(config)
        results, df = model.run_simulation()
        
        if results:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Jam Selesai", results['jam_selesai_terakhir'].strftime('%H:%M'))
            m2.metric("Durasi Total", f"{results['waktu_selesai_terakhir']:.1f} min")
            m3.metric("Avg Proses", f"{results['avg_durasi_proses']:.2f} min")
            m4.metric("Utilisasi", f"{results['utilitas_rata_rata']:.1f}%")
            
            st.plotly_chart(create_process_distribution(df), use_container_width=True)
            st.plotly_chart(create_timeline_chart(df), use_container_width=True)

if __name__ == "__main__":
    main()