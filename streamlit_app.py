import streamlit as st
import simpy
import random
import numpy as np
from datetime import datetime, timedelta
import pandas as pd
from dataclasses import dataclass
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================
# KONFIGURASI SIMULASI
# ============================
@dataclass
class Config:
    """Konfigurasi parameter simulasi Piket IT Del"""
    # Parameter dasar
    JUMLAH_MEJA: int = 60
    OMPRENG_PER_MEJA: int = 3
    TOTAL_OMPRENG: int = 180
    NUM_PETUGAS: int = 7
    
    # Distribusi waktu (dalam menit)
    MIN_LAUK: float = 0.5   # 30 detik
    MAX_LAUK: float = 1.0   # 60 detik
    
    MIN_ANGKUT: float = 0.33 # 20 detik
    MAX_ANGKUT: float = 1.0  # 60 detik
    
    MIN_NASI: float = 0.5    # 30 detik
    MAX_NASI: float = 1.0    # 60 detik
    
    BATCH_MIN: int = 4
    BATCH_MAX: int = 7
    
    # Jam mulai
    START_HOUR: int = 7
    START_MINUTE: int = 0
    
    # Seed untuk reproduktibilitas
    RANDOM_SEED: int = 42

# ============================
# MODEL SIMULASI
# ============================
class PiketKantinDES:
    def __init__(self, config: Config):
        self.config = config
        self.env = simpy.Environment()
        
        # Resources: 7 Mahasiswa petugas piket
        self.petugas = simpy.Resource(self.env, capacity=config.NUM_PETUGAS)
        
        # Buffer antar tahap
        self.siap_angkut = simpy.Store(self.env)
        self.siap_nasi = simpy.Store(self.env)
        
        # Statistik
        self.statistics = {
            'ompreng_data': [],
            'queue_lengths': [],
            'utilization': []
        }
        
        # Waktu mulai simulasi
        self.start_time = datetime(2026, 2, 11, config.START_HOUR, config.START_MINUTE)
        self.selesai_count = 0
        
        # Set random seed
        random.seed(config.RANDOM_SEED)
        np.random.seed(config.RANDOM_SEED)
    
    def waktu_ke_jam(self, waktu_simulasi: float) -> datetime:
        return self.start_time + timedelta(minutes=waktu_simulasi)
    
    def proses_lauk(self, ompreng_id: int):
        """Tahap 1: Memasukkan lauk"""
        with self.petugas.request() as req:
            yield req
            durasi = random.uniform(self.config.MIN_LAUK, self.config.MAX_LAUK)
            yield self.env.timeout(durasi)
            yield self.siap_angkut.put({'id': ompreng_id, 'start_time': self.env.now - durasi})

    def proses_angkut(self):
        """Tahap 2: Mengangkat ompreng ke meja (Batch 4-7)"""
        while self.selesai_count < self.config.TOTAL_OMPRENG:
            batch_size = random.randint(self.config.BATCH_MIN, self.config.BATCH_MAX)
            items = []
            
            # Ambil ompreng dari buffer lauk
            for _ in range(batch_size):
                if (self.selesai_count + len(items)) < self.config.TOTAL_OMPRENG:
                    if len(self.siap_angkut.items) > 0:
                        item = yield self.siap_angkut.get()
                        items.append(item)
                    else: break
            
            if items:
                with self.petugas.request() as req:
                    yield req
                    durasi = random.uniform(self.config.MIN_ANGKUT, self.config.MAX_ANGKUT)
                    yield self.env.timeout(durasi)
                    for item in items:
                        yield self.siap_nasi.put(item)
            else:
                yield self.env.timeout(0.05)

    def proses_nasi(self):
        """Tahap 3: Menambahkan nasi di meja"""
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
                # Catat utilisasi petugas (berapa yang sedang sibuk)
                self.statistics['utilization'].append({
                    'time': self.env.now,
                    'in_use': self.petugas.count
                })

    def run_simulation(self):
        # Trigger proses lauk untuk semua ompreng
        for i in range(self.config.TOTAL_OMPRENG):
            self.env.process(self.proses_lauk(i))
        
        # Jalankan proses angkut dan nasi
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
            'max_durasi_proses': df['durasi_total'].max(),
            'min_durasi_proses': df['durasi_total'].min(),
            'utilitas_rata_rata': np.mean([u['in_use'] for u in self.statistics['utilization']]) / self.config.NUM_PETUGAS * 100
        }
        
        return results, df

# ============================
# FUNGSI VISUALISASI PLOTLY
# ============================
def create_process_distribution(df):
    fig = px.histogram(
        df, x='durasi_total', nbins=20,
        title='📊 Distribusi Durasi Total per Ompreng',
        labels={'durasi_total': 'Durasi (menit)', 'count': 'Jumlah Ompreng'},
        color_discrete_sequence=['#1f77b4'], opacity=0.8
    )
    fig.update_layout(xaxis_title="Menit", yaxis_title="Frekuensi")
    return fig

def create_timeline_chart(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['waktu_selesai'], y=df.index + 1,
        mode='lines+markers', name='Penyelesaian',
        line=dict(color='green'),
        hovertemplate='Ompreng ke-%{y}<br>Selesai: %{x:.2f} menit<extra></extra>'
    ))
    fig.update_layout(
        title='📈 Timeline Penyelesaian Ompreng',
        xaxis_title="Waktu Simulasi (menit)",
        yaxis_title="Total Ompreng Selesai",
        hovermode="x unified"
    )
    return fig

def create_utilization_gauge(results):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=results['utilitas_rata_rata'],
        title={'text': "Rata-rata Utilisasi Petugas (%)"},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 50], 'color': "lightgray"},
                {'range': [50, 80], 'color': "gray"},
                {'range': [80, 100], 'color': "red"}
            ]
        }
    ))
    fig.update_layout(height=300)
    return fig

# ============================
# APLIKASI STREAMLIT
# ============================
def main():
    st.set_page_config(page_title="Simulasi Piket IT Del", page_icon="🍱", layout="wide")
    
    with st.sidebar:
        st.subheader("⚙️ Parameter Piket")
        num_petugas = st.slider("Jumlah Petugas Mahasiswa", 1, 15, 7)
        total_meja = st.number_input("Jumlah Meja", value=60)
        
        st.markdown("---")
        st.subheader("⏱️ Parameter Waktu (Menit)")
        lauk_range = st.slider("Waktu Isi Lauk", 0.1, 2.0, (0.5, 1.0))
        angkut_range = st.slider("Waktu Angkut", 0.1, 2.0, (0.33, 1.0))
        nasi_range = st.slider("Waktu Isi Nasi", 0.1, 2.0, (0.5, 1.0))
        
        st.markdown("---")
        run_simulation = st.button("🚀 Jalankan Simulasi", type="primary", use_container_width=True)

    st.title("🍱 Simulasi Sistem Piket Mahasiswa IT Del")
    st.markdown("Menganalisis efisiensi pengerjaan ompreng di kantin dari tahap lauk, angkut, hingga nasi.")

    if run_simulation:
        config = Config(
            NUM_PETUGAS=num_petugas,
            JUMLAH_MEJA=total_meja,
            TOTAL_OMPRENG=total_meja * 3,
            MIN_LAUK=lauk_range[0], MAX_LAUK=lauk_range[1],
            MIN_ANGKUT=angkut_range[0], MAX_ANGKUT=angkut_range[1],
            MIN_NASI=nasi_range[0], MAX_NASI=nasi_range[1]
        )
        
        model = PiketKantinDES(config)
        results, df = model.run_simulation()
        
        if results:
            st.success(f"✅ Simulasi Selesai! {config.TOTAL_OMPRENG} ompreng diproses.")
            
            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Jam Selesai", results['jam_selesai_terakhir'].strftime('%H:%M:%S'))
            m2.metric("Durasi Total", f"{results['waktu_selesai_terakhir']:.1f} menit")
            m3.metric("Avg Proses/Ompreng", f"{results['avg_proses_durasi']:.2f} m" if 'avg_proses_durasi' in results else f"{results['avg_durasi_proses']:.2f} m")
            m4.metric("Utilisasi Petugas", f"{results['utilitas_rata_rata']:.1f}%")

            # Visualisasi
            st.markdown("---")
            col_a, col_b = st.columns(2)
            with col_a:
                st.plotly_chart(create_process_distribution(df), use_container_width=True)
            with col_b:
                st.plotly_chart(create_timeline_chart(df), use_container_width=True)
            
            st.markdown("---")
            col_c, col_d = st.columns([1, 2])
            with col_c:
                st.plotly_chart(create_utilization_gauge(results), use_container_width=True)
            with col_d:
                st.subheader("📄 Sampel Data Penyelesaian")
                st.dataframe(df.tail(10), use_container_width=True)
    else:
        st.info("Atur parameter di samping dan klik tombol **Jalankan Simulasi** untuk melihat hasil.")

if __name__ == "__main__":
    main()