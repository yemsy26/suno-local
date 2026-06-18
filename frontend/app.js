// ──────────────────────────────────────────────────────────────────────────────
// Suno-Local - Frontend Logic (Vanilla JS)
// Se comunica con FastAPI (http://localhost:8765)
// ──────────────────────────────────────────────────────────────────────────────

const API_BASE = window.location.origin;
let currentJobId = null;
let eventSource = null;

const navItems = document.querySelectorAll('.nav-item');
const views = document.querySelectorAll('.view');

// Audio Player Elements
const globalAudio = document.getElementById('global-audio');
const btnPlayPause = document.getElementById('btn-play-pause');
const audioProgress = document.getElementById('audio-progress');
const timeCurrent = document.getElementById('time-current');
const timeTotal = document.getElementById('time-total');
const playerTitle = document.getElementById('player-title');
const progressBarContainer = document.querySelector('.progress-bar-container');

// ── UTILITIES ──
function showNotification(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.cssText = `
        position: fixed; top: 20px; right: 20px; padding: 15px 25px;
        background: ${type === 'error' ? '#ff4d4d' : '#2ecc71'};
        color: white; border-radius: 8px; font-weight: bold;
        z-index: 9999; box-shadow: 0 4px 15px rgba(0,0,0,0.3);
        animation: slideIn 0.3s ease-out;
    `;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function startEventStream(jobId, context) {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`${API_BASE}/jobs/${jobId}/stream`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        const logsContainer = document.getElementById(`${context}-logs`);
        const progressFill = document.getElementById(`${context}-progress-fill`);

        if (data.type === 'log' || data.type === 'checkpoint') {
            const div = document.createElement('div');
            div.textContent = data.message || `[${data.stage}] Procesando...`;
            if (logsContainer) {
                logsContainer.appendChild(div);
                logsContainer.scrollTop = logsContainer.scrollHeight;
            }
            if (progressFill && data.stage) {
                if (data.stage === 'ACESTEP_GENERATE') progressFill.style.width = '20%';
                if (data.stage === 'UVR5_SEPARATE') progressFill.style.width = '40%';
                if (data.stage === 'DEEPFILTER_REPAIR') progressFill.style.width = '60%';
                if (data.stage === 'RVC_CLONE') progressFill.style.width = '80%';
            }
        } else if (data.type === 'completed') {
            eventSource.close();
            const div = document.createElement('div');
            div.textContent = '✅ Proceso Completado Exitosamente.';
            div.style.color = '#2ecc71';
            if (logsContainer) {
                logsContainer.appendChild(div);
                logsContainer.scrollTop = logsContainer.scrollHeight;
            }
            if (progressFill) progressFill.style.width = '100%';
            
            showNotification('Proceso completado.', 'success');
            
            const btn = context === 'studio' ? document.getElementById('generate-btn') : document.getElementById('btn-repair');
            if (btn) {
                btn.disabled = false;
                if (context === 'studio') {
                    btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Generar Canción Completa';
                    btn.classList.add('hidden');
                    const resetBtn = document.getElementById('btn-reset-studio');
                    if (resetBtn) resetBtn.classList.remove('hidden');
                } else {
                    btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Limpiar Audio';
                }
            }
            
            if (data.output_path && context === 'studio') {
                // Auto-play al completar: Buscar el track más reciente en galería
                setTimeout(async () => {
                    try {
                        const galleryRes = await fetch(`${API_BASE}/gallery?limit=1`);
                        const galleryData = await galleryRes.json();
                        if (galleryData.tracks && galleryData.tracks.length > 0) {
                            const lastTrack = galleryData.tracks[0];
                            playAudio(`${API_BASE}/gallery/${lastTrack.id}/download`, lastTrack.title);
                            showNotification(`🎵 Reproduciendo: ${lastTrack.title}`, 'success');
                        }
                    } catch(e) { console.warn('Auto-play fallback failed', e); }
                }, 800);
                // Mostrar botón de abort ocultado
                const abortBtn = document.getElementById('btn-abort-studio');
                if (abortBtn) abortBtn.classList.add('hidden');
            }
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        showNotification('Conexión perdida o finalizada por error.', 'error');
        const btn = context === 'studio' ? document.getElementById('generate-btn') : document.getElementById('btn-repair');
        if (btn) {
            btn.disabled = false;
            if (context === 'studio') {
                btn.innerHTML = '<i class="fa-solid fa-bolt"></i> Generar Canción Completa';
            } else {
                btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Limpiar Audio';
            }
        }
    };
}



// ── NAVIGATION ──
navItems.forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const targetView = item.getAttribute('data-view');
        
        navItems.forEach(nav => nav.classList.remove('active'));
        item.classList.add('active');
        
        views.forEach(view => view.classList.remove('active'));
        document.getElementById(`view-${targetView}`).classList.add('active');

        if (targetView === 'gallery') {
            loadGallery();
        }
    });
});




// ── GALLERY ──
async function loadGallery() {
    const grid = document.getElementById('gallery-grid');
    try {
        const res = await fetch(`${API_BASE}/gallery`);
        const data = await res.json();
        
        grid.innerHTML = '';
        if (data.tracks.length === 0) {
            grid.innerHTML = '<p style="color: var(--text-secondary)">No hay pistas en la galería.</p>';
            return;
        }

        data.tracks.forEach(track => {
            const el = document.createElement('div');
            el.className = 'gallery-item';
            el.innerHTML = `
                <div class="gallery-cover">
                    ${track.metadata?.diagnostic?.has_warnings ? '<div style="position: absolute; top: 5px; right: 5px; background: rgba(255,50,50,0.8); color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; z-index: 10;" title="Aviso del Espectrómetro: Posible corte o clipping"><i class="fa-solid fa-triangle-exclamation"></i> Alerta</div>' : ''}
                    <i class="fa-solid fa-music"></i>
                    <div class="gallery-play"><i class="fa-solid fa-play"></i></div>
                </div>
                <div class="gallery-title">${track.title}</div>
                <div class="gallery-artist" style="font-size: 13px; color: #a0a0a0; margin-bottom: 5px;">${track.metadata?.artista || track.metadata?.artist || 'Artista Desconocido'}</div>
                <div class="gallery-genre">${track.genre || 'Generado'}</div>
                <div class="gallery-meta" style="color: #4facfe; font-size: 11px;">
                    <i class="fa-solid fa-microphone"></i> Voz: ${track.metadata?.voice_model || 'Predeterminada'}
                </div>
                <div class="gallery-meta">
                    <span>${track.bpm ? track.bpm + ' BPM' : ''}</span>
                    <span>${new Date(track.created_at).toLocaleDateString()}</span>
                </div>
                <div style="display: flex; gap: 8px; margin-top: 10px; z-index: 10;">
                    <button class="btn-secondary" style="flex: 1; padding: 4px; font-size: 12px;" onclick="renameTrack(event, ${track.id}, '${track.title.replace(/'/g, "\\'")}')">
                        <i class="fa-solid fa-pen"></i> Editar
                    </button>
                    <button class="btn-secondary ${track.favorite ? 'fav-active' : ''}" style="padding: 4px 8px; font-size: 12px; ${track.favorite ? 'color:#f5c518;' : ''}" onclick="toggleFav(event, ${track.id}, this)" title="Favorito">
                        <i class="fa-${track.favorite ? 'solid' : 'regular'} fa-star"></i>
                    </button>
                    <a href="${API_BASE}/gallery/${track.id}/download" target="_blank" class="btn-secondary" style="flex: 1; padding: 4px; font-size: 12px; text-decoration: none; text-align: center;" onclick="event.stopPropagation()">
                        <i class="fa-solid fa-download"></i> WAV
                    </a>
                </div>
            `;
            
            el.addEventListener('click', () => {
                playAudio(`${API_BASE}/gallery/${track.id}/download`, track.title);
            });
            
            grid.appendChild(el);
        });
    } catch (e) {
        console.error("Error loading gallery", e);
    }
}

// Botones de la galería: buscar y recargar
document.addEventListener('DOMContentLoaded', () => {
    const searchBtn = document.getElementById('gallery-search-btn');
    const reloadBtn = document.getElementById('gallery-reload-btn');
    const searchInput = document.getElementById('gallery-search-input');

    if (reloadBtn) reloadBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        loadGallery();
    });

    if (searchBtn && searchInput) {
        const doSearch = async () => {
            const q = searchInput.value.trim();
            if (!q) { loadGallery(); return; }
            const grid = document.getElementById('gallery-grid');
            grid.innerHTML = '<p style="color: var(--text-secondary)">Buscando...</p>';
            try {
                const res = await fetch(`${API_BASE}/gallery/search/${encodeURIComponent(q)}`);
                const data = await res.json();
                grid.innerHTML = '';
                if (!data.tracks || data.tracks.length === 0) {
                    grid.innerHTML = '<p style="color: var(--text-secondary)">Sin resultados para: ' + q + '</p>';
                    return;
                }
                data.tracks.forEach(track => {
                    const el = document.createElement('div');
                    el.className = 'gallery-item';
                    el.innerHTML = `<div class="gallery-cover"><i class="fa-solid fa-music"></i><div class="gallery-play"><i class="fa-solid fa-play"></i></div></div><div class="gallery-title">${track.title}</div><div class="gallery-genre">${track.genre || 'Generado'}</div>`;
                    el.addEventListener('click', () => playAudio(`${API_BASE}/gallery/${track.id}/download`, track.title));
                    grid.appendChild(el);
                });
            } catch(e) { console.error('Search error', e); }
        };
        searchBtn.addEventListener('click', doSearch);
        searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });
    }
});

window.renameTrack = async (event, trackId, currentTitle) => {
    event.stopPropagation();
    const newTitle = prompt("Nuevo nombre para la canción:", currentTitle);
    if (!newTitle || newTitle.trim() === currentTitle) return;
    try {
        const res = await fetch(`${API_BASE}/gallery/${trackId}`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: newTitle.trim()})
        });
        if (res.ok) {
            loadGallery();
        } else {
            alert("Error al renombrar la canción.");
        }
    } catch (e) {
        console.error("Rename error", e);
    }
};

window.toggleFav = async (event, trackId, btn) => {
    event.stopPropagation();
    try {
        const res = await fetch(`${API_BASE}/gallery/${trackId}/favorite`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            const icon = btn.querySelector('i');
            if (data.favorite) {
                icon.className = 'fa-solid fa-star';
                btn.style.color = '#f5c518';
            } else {
                icon.className = 'fa-regular fa-star';
                btn.style.color = '';
            }
        }
    } catch(e) { console.error("Fav error", e); }
};

// ── GLOBAL AUDIO PLAYER ──
function playAudio(url, title) {
    globalAudio.src = url;
    globalAudio.play();
    playerTitle.textContent = title;
    btnPlayPause.innerHTML = '<i class="fa-solid fa-pause"></i>';
}

btnPlayPause.addEventListener('click', () => {
    if (globalAudio.paused) {
        if(globalAudio.src && globalAudio.src !== window.location.href) {
            globalAudio.play();
            btnPlayPause.innerHTML = '<i class="fa-solid fa-pause"></i>';
        }
    } else {
        globalAudio.pause();
        btnPlayPause.innerHTML = '<i class="fa-solid fa-play"></i>';
    }
});

globalAudio.addEventListener('timeupdate', () => {
    const current = globalAudio.currentTime;
    const duration = globalAudio.duration || 0;
    
    timeCurrent.textContent = formatTime(current);
    timeTotal.textContent = formatTime(duration);
    
    const percent = duration ? (current / duration) * 100 : 0;
    audioProgress.style.width = `${percent}%`;
});

globalAudio.addEventListener('ended', () => {
    btnPlayPause.innerHTML = '<i class="fa-solid fa-play"></i>';
    audioProgress.style.width = '0%';
});

progressBarContainer.addEventListener('click', (e) => {
    const rect = progressBarContainer.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    if (globalAudio.duration) globalAudio.currentTime = pos * globalAudio.duration;
});
// Soporte touch para dispositivos móviles
progressBarContainer.addEventListener('touchstart', (e) => {
    const rect = progressBarContainer.getBoundingClientRect();
    const touch = e.touches[0];
    const pos = (touch.clientX - rect.left) / rect.width;
    if (globalAudio.duration) globalAudio.currentTime = pos * globalAudio.duration;
    e.preventDefault();
}, { passive: false });

function formatTime(seconds) {
    if (isNaN(seconds)) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
}

// ── RUTA 2: REMASTERIZACIÓN AUDIO-TO-AUDIO ──────────────────────────────────

let remasterFile = null;
let remasterJobId = null;
let remasterEventSource = null;

const btnRemaster = document.getElementById('btn-remaster');
const remasterFileInput = document.getElementById('remaster-file-input');
const remasterDropzone = document.getElementById('remaster-dropzone');
const remasterFileInfo = document.getElementById('remaster-file-info');
const remasterFileName = document.getElementById('remaster-file-name');
const remasterFileSize = document.getElementById('remaster-file-size');
const remasterClearBtn = document.getElementById('remaster-clear-btn');
const remasterProgress = document.getElementById('remaster-progress');
const remasterTerminal = document.getElementById('remaster-terminal');
const remasterSteps = document.querySelectorAll('[data-step-rm]');

// Drag & Drop handlers
remasterDropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    remasterDropzone.classList.add('dragover');
});
remasterDropzone.addEventListener('dragleave', () => {
    remasterDropzone.classList.remove('dragover');
});
remasterDropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    remasterDropzone.classList.remove('dragover');
    const f = e.dataTransfer.files[0];
    if (f) setRemasterFile(f);
});

// File input change
remasterFileInput.addEventListener('change', (e) => {
    if (e.target.files[0]) setRemasterFile(e.target.files[0]);
});

// Clear button
remasterClearBtn.addEventListener('click', clearRemasterFile);

function setRemasterFile(file) {
    remasterFile = file;
    remasterFileName.textContent = file.name;
    const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
    remasterFileSize.textContent = `${sizeMB} MB`;
    remasterFileInfo.classList.remove('hidden');
    remasterDropzone.style.opacity = '0.5';
    btnRemaster.disabled = false;
}

function clearRemasterFile() {
    remasterFile = null;
    remasterFileInput.value = '';
    remasterFileInfo.classList.add('hidden');
    remasterDropzone.style.opacity = '1';
    btnRemaster.disabled = true;
}

// Launch remaster
btnRemaster.addEventListener('click', async () => {
    if (!remasterFile) return;

    // Reset UI
    remasterTerminal.innerHTML = '';
    remasterSteps.forEach(s => s.classList.remove('active', 'completed'));
    remasterProgress.classList.remove('hidden');
    btnRemaster.disabled = true;
    btnRemaster.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Procesando...';

    const formData = new FormData();
    formData.append('file', remasterFile);
    const voiceModel = document.getElementById('global-voice-selector')?.value;
    if (voiceModel) {
        formData.append('voice_model', voiceModel);
    }
    const pitchShift = document.getElementById('global-pitch-selector')?.value;
    if (pitchShift) {
        formData.append('pitch_shift', pitchShift);
    }

    try {
        const res = await fetch(`${API_BASE}/remaster`, {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json();
            appendRemasterLog(`Error del servidor: ${err.detail || res.statusText}`, 'log-err');
            resetRemasterButton();
            return;
        }

        const data = await res.json();
        remasterJobId = data.job_id;
        appendRemasterLog(`✅ Job iniciado: ${remasterJobId}`, 'log-info');
        startRemasterStream(remasterJobId);

    } catch (err) {
        appendRemasterLog(`Error crítico: ${err.message}`, 'log-err');
        resetRemasterButton();
    }
});

function startRemasterStream(jobId) {
    if (remasterEventSource) remasterEventSource.close();

    remasterEventSource = new EventSource(`${API_BASE}/jobs/${jobId}/stream`);

    remasterEventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'log') {
            const msg = data.message;
            let cls = 'log-info';
            if (msg.includes('WARN')) cls = 'log-warn';
            if (msg.includes('ERR') || msg.includes('CRIT')) cls = 'log-err';
            appendRemasterLog(msg, cls);

            // Step visual update
            if (msg.includes('ETAPA 3') || msg.includes('UVR5')) updateRemasterStep('UVR5_SEPARATE');
            if (msg.includes('ETAPA 4') || msg.includes('RVC'))  updateRemasterStep('RVC_CLONE');
            if (msg.includes('ETAPA 5') || msg.includes('FFmpeg') || msg.includes('Mezcla')) updateRemasterStep('MIX_AND_MASTER');

        } else if (data.type === 'completed') {
            appendRemasterLog('✨ Remasterización Completada Exitosamente.', 'log-info');
            remasterEventSource.close();
            resetRemasterButton();
            remasterSteps.forEach(s => s.classList.add('completed'));

            if (data.output_path) {
                playAudio(`${API_BASE}/audio/${jobId}`, `Remaster: ${remasterFile ? remasterFile.name : jobId}`);
            }
        } else if (data.type === 'heartbeat') {
            // ignore silently
        }
    };

    remasterEventSource.onerror = () => {
        appendRemasterLog('⚠️ Conexión perdida con el servidor.', 'log-warn');
        remasterEventSource.close();
        resetRemasterButton();
    };
}

function appendRemasterLog(msg, cls) {
    const div = document.createElement('div');
    div.className = cls || 'log-info';
    div.textContent = msg;
    remasterTerminal.appendChild(div);
    remasterTerminal.scrollTop = remasterTerminal.scrollHeight;
}

function updateRemasterStep(stepName) {
    let found = false;
    remasterSteps.forEach(step => {
        if (found) return;
        if (step.getAttribute('data-step-rm') === stepName) {
            step.classList.add('active');
            step.classList.remove('completed');
            found = true;
        } else {
            step.classList.remove('active');
            step.classList.add('completed');
        }
    });
}

function resetRemasterButton() {
    btnRemaster.disabled = false;
    btnRemaster.innerHTML = '<i class="fa-solid fa-microphone-lines"></i> Aplicar Voz RVC';
}




async function loadVoices() {
    const selector = document.getElementById('global-voice-selector');
    if (!selector) return;
    try {
        const res = await fetch(API_BASE + '/api/voices');
        if (!res.ok) throw new Error('Failed to fetch voices');
        const data = await res.json();
        selector.innerHTML = '<option value="none">❌ Ninguno (Usar solo la Sintética)</option>';
        if (data.voices.length === 0) {
            return;
        }
        
        data.voices.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.model_path;
            opt.textContent = v.name;
            selector.appendChild(opt);
        });

        // Restaurar el modelo guardado si existe
        const savedVoice = localStorage.getItem('selectedVoiceModel');
        if (savedVoice) {
            selector.value = savedVoice;
        }

        // Guardar el modelo cuando el usuario lo cambie
        selector.addEventListener('change', (e) => {
            localStorage.setItem('selectedVoiceModel', e.target.value);
        });
    } catch (err) {
        console.error('Error loading voices:', err);
        selector.innerHTML = '<option value=\"\">Error cargando voces</option>';
    }
}

document.addEventListener('DOMContentLoaded', loadVoices);
document.addEventListener('DOMContentLoaded', loadGallery);
document.addEventListener('DOMContentLoaded', initRepair);
document.addEventListener('DOMContentLoaded', initStudio);



// -----------------------------------------------------------------------------
// REPAIR LOGIC
// -----------------------------------------------------------------------------

function initRepair() {
    const dropzone = document.getElementById('repair-dropzone');
    const fileInput = document.getElementById('repair-file-input');
    const fileInfo = document.getElementById('repair-file-info');
    const fileName = document.getElementById('repair-file-name');
    const fileSize = document.getElementById('repair-file-size');
    const clearBtn = document.getElementById('repair-clear-btn');
    const btnRepair = document.getElementById('btn-repair');
    
    let selectedFile = null;

    function handleFile(file) {
        if (!file) {
            showNotification('Por favor, selecciona un archivo válido.', 'error');
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        fileSize.textContent = (file.size / (1024 * 1024)).toFixed(1) + ' MB';
        
        dropzone.classList.add('hidden');
        fileInfo.classList.remove('hidden');
        btnRepair.disabled = false;
    }

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFile(e.target.files[0]);
    });

    clearBtn.addEventListener('click', () => {
        selectedFile = null;
        fileInput.value = '';
        fileInfo.classList.add('hidden');
        dropzone.classList.remove('hidden');
        btnRepair.disabled = true;
    });

    btnRepair.addEventListener('click', async () => {
        if (!selectedFile) return;

        btnRepair.disabled = true;
        btnRepair.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Iniciando...';
        
        document.getElementById('repair-progress').classList.remove('hidden');
        const logsContainer = document.getElementById('repair-logs');
        logsContainer.innerHTML = '';
        
        document.querySelectorAll('.step[data-step-rp]').forEach(el => {
            el.classList.remove('active', 'completed', 'error');
        });

        const formData = new FormData();
        formData.append('file', selectedFile);

        try {
            const res = await fetch(`${API_BASE}/repair`, {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error al iniciar reparación');
            }

            const data = await res.json();
            startEventStream(data.job_id, 'repair');
            showNotification('Reparación iniciada', 'success');
        } catch (error) {
            console.error(error);
            showNotification(error.message, 'error');
            btnRepair.disabled = false;
            btnRepair.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Limpiar Audio';
        }
    });
}

// -----------------------------------------------------------------------------
// STUDIO LOGIC
// -----------------------------------------------------------------------------

function initStudio() {
    const btnGenerate = document.getElementById('generate-btn');
    const btnGenerateLyrics = document.getElementById('generate-lyrics-btn');
    if (!btnGenerate) return;

    if (btnGenerateLyrics) {
        btnGenerateLyrics.addEventListener('click', async () => {
            const topic = document.getElementById('topic-input').value.trim();
            const style = document.getElementById('style-input').value.trim();
            
            if (!topic) {
                showNotification('Falta información: Por favor, escribe un tema o idea en el cuadro de "Tema de la Canción" para que la IA sepa qué redactar.', 'error');
                return;
            }

            btnGenerateLyrics.disabled = true;
            btnGenerateLyrics.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Generando...';
            
            try {
                const formData = new FormData();
                formData.append('topic', topic);
                if (style) {
                    formData.append('style', style);
                }
                const res = await fetch(`${API_BASE}/generate_lyrics`, {
                    method: 'POST',
                    body: formData
                });

                if (!res.ok) {
                    if (res.status === 404) {
                        throw new Error('Servicio no encontrado. Por favor, reinicia la consola (run.bat) para cargar el nuevo motor IA.');
                    }
                    throw new Error('Error de conexión con el motor IA local.');
                }

                const data = await res.json();
                document.getElementById('lyrics-input').value = data.lyrics;
                if (data.title) {
                    document.getElementById('song-title').value = data.title;
                }
                showNotification('Letra y Título generados con éxito. Ya puedes editarlos o proceder a generar la canción.', 'success');
            } catch (error) {
                console.error(error);
                showNotification(error.message, 'error');
            } finally {
                btnGenerateLyrics.disabled = false;
                btnGenerateLyrics.innerHTML = '<i class="fa-solid fa-pen-nib"></i> Generar Letra (IA)';
            }
        });
    }

    btnGenerate.addEventListener('click', async () => {
        const lyrics = document.getElementById('lyrics-input').value.trim();
        const style = document.getElementById('style-input').value.trim();
        const voiceModel = document.getElementById('global-voice-selector')?.value;
        const title = document.getElementById('song-title')?.value.trim();
        
        if (!lyrics) {
            showNotification('Falta Letra: Por favor, escribe la letra de la canción o utiliza el botón "Generar Letra (IA)".', 'error');
            return;
        }
        
        if (!style) {
            showNotification('Falta Estilo Musical: Escribe un género, instrumentos o estilo (Ej: "Pop latino, guitarra").', 'error');
            return;
        }
        
        // Acepta "none" como voz válida (usar solo la voz sintética, sin clon)
        // Solo bloquea si el selector está vacío por completo (error de carga de UI)
        if (voiceModel === undefined || voiceModel === null || voiceModel === '') {
            showNotification('Error del sistema: No se pudo leer el selector de voz. Recarga la página.', 'error');
            return;
        }

        btnGenerate.disabled = true;
        btnGenerate.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Generando...';
        
        document.getElementById('studio-status').classList.remove('hidden');
        document.getElementById('studio-progress-fill').style.width = '0%';
        document.getElementById('studio-logs').innerHTML = '';

        const formData = new FormData();
        formData.append('prompt', lyrics);
        if (style) {
            formData.append('style', style);
        }

        if (voiceModel) {
            formData.append('voice_model', voiceModel);
        }

        const syntheticVoiceSeed = document.getElementById('synthetic-voice-selector')?.value || '-1';
        formData.append('synthetic_voice_seed', syntheticVoiceSeed);

        if (title) {
            formData.append('title', title);
        }

        const pitchShift = document.getElementById('global-pitch-selector')?.value;
        if (pitchShift) {
            formData.append('pitch_shift', pitchShift);
        }

        try {
            const res = await fetch(`${API_BASE}/generate`, {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error al iniciar generación');
            }

            const data = await res.json();
            currentJobId = data.job_id;
            startEventStream(data.job_id, 'studio');
            showNotification('Generación iniciada', 'success');
            // Mostrar botón de abortar
            const abortBtn = document.getElementById('btn-abort-studio');
            if (abortBtn) {
                abortBtn.classList.remove('hidden');
                abortBtn.onclick = async () => {
                    if (!currentJobId) return;
                    try {
                        await fetch(`${API_BASE}/jobs/${currentJobId}/abort`, { method: 'POST' });
                        showNotification('⛔ Generación abortada.', 'error');
                        abortBtn.classList.add('hidden');
                        btnGenerate.disabled = false;
                        btnGenerate.innerHTML = '<i class="fa-solid fa-bolt"></i> Generar Canción Completa';
                        if (eventSource) eventSource.close();
                    } catch(e) { console.error('Abort failed', e); }
                };
            }
        } catch (error) {
            console.error(error);
            showNotification(error.message, 'error');
            btnGenerate.disabled = false;
            btnGenerate.innerHTML = '<i class="fa-solid fa-bolt"></i> Generar Canción Completa';
        }
    });

    const btnResetStudio = document.getElementById('btn-reset-studio');
    if (btnResetStudio) {
        btnResetStudio.addEventListener('click', () => {
            document.getElementById('topic-input').value = '';
            document.getElementById('style-input').value = '';
            document.getElementById('song-title').value = '';
            document.getElementById('lyrics-input').value = '';
            document.getElementById('studio-status').classList.add('hidden');
            document.getElementById('studio-logs').innerHTML = '';
            btnGenerate.classList.remove('hidden');
            btnResetStudio.classList.add('hidden');
            showNotification('Estudio reiniciado. Listo para crear.', 'info');
        });
    }
}
