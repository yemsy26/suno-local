import librosa
import numpy as np
import sys
import os

def analyze_audio(vocal_path, beat_path):
    report = []
    report.append("==================================================")
    report.append(" REPORTE PROFESIONAL DE CALIDAD")
    report.append("==================================================")

    try:
        # Load vocal to find intro length and vocal presence
        y_voc, sr_voc = librosa.load(vocal_path, sr=22050)
        
        # Calculate RMS energy to find the first vocal onset
        rms = librosa.feature.rms(y=y_voc)[0]
        threshold = 0.01  # Energy threshold for vocals
        non_silent_frames = np.where(rms > threshold)[0]
        
        if len(non_silent_frames) > 0:
            first_frame = non_silent_frames[0]
            intro_duration = librosa.frames_to_time(first_frame, sr=sr_voc)
            report.append(f" Duracion de la Intro: {intro_duration:.1f} segundos")
            if intro_duration > 15.0:
                report.append("   [ADVERTENCIA]: Intro instrumental muy larga antes de cantar.")
            elif intro_duration < 2.0:
                report.append("   [OK]: La voz entra casi de inmediato.")
            else:
                report.append("   [OK]: Intro de duracion normal.")
                
            # Vocal presence percentage
            total_duration = librosa.get_duration(y=y_voc, sr=sr_voc)
            active_duration = len(non_silent_frames) * librosa.frames_to_time(1, sr=sr_voc)
            presence_percent = (active_duration / total_duration) * 100
            report.append(f" Presencia Vocal: {presence_percent:.1f}% de la pista")
            if presence_percent < 20.0:
                report.append("   [ADVERTENCIA]: Muy poca letra cantada, posible falta de ritmo o silencios graves.")
            else:
                report.append("   [OK]: Volumen y flujo vocal constante detectado.")
        else:
            report.append(" [ERROR CRITICO]: No se detecto ninguna voz en la pista aisalda.")

        # Load beat to estimate BPM
        y_beat, sr_beat = librosa.load(beat_path, sr=22050)
        tempo, _ = librosa.beat.beat_track(y=y_beat, sr=sr_beat)
        
        # tempo in newer librosa can be an array or float
        if isinstance(tempo, np.ndarray):
            tempo_val = tempo[0]
        else:
            tempo_val = tempo
            
        report.append(f" Ritmo detectado (BPM): {tempo_val:.1f}")
        if tempo_val < 60 or tempo_val > 200:
            report.append("   [ADVERTENCIA]: Ritmo anormal o descoordinado.")
        else:
            report.append("   [OK]: Ritmo estable dentro de los parametros de pop/latino.")

    except Exception as e:
        report.append(f" Error durante el analisis: {str(e)}")

    report.append("==================================================")
    
    # Print report
    for line in report:
        print(line)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python audio_analyzer.py <vocal_path> <beat_path>")
        sys.exit(1)
        
    vocal_file = sys.argv[1]
    beat_file = sys.argv[2]
    
    analyze_audio(vocal_file, beat_file)
