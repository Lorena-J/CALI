# Contexto de CALI

Revisión inicial: 2026-10-27. Este fichero recoge el comportamiento observado en
el código del árbol de trabajo, incluidas funciones todavía sin seguimiento en
Git. Actualizarlo cuando cambien los formatos, la sincronización, el flujo de
trabajo o las decisiones confirmadas por la responsable del proyecto.

## Propósito y alcance

Cambio de nombre (2026-10-27): el proyecto pasa de MINISYNC a CALI, como el
logo de `icons/logo/`. Las rutas `minisync*` antiguas que aparecen abajo y en
`docs/` son registros históricos de validación; no renombrarlas. El entorno
Conda de la interfaz sigue llamándose `mini2p-sync`.


CALI (CAlcium LInked Behavior explorer; antes MINISYNC) es una aplicación local de escritorio en Python para inspeccionar y
alinear adquisición Mini2P y vídeo de comportamiento usando CSV de pulsos TTL.
Permite ver imágenes, alinear una coordenada de tracking, consultar resultados
CaImAn CNMF y describir asociaciones entre actividad de calcio y movimiento.
Puede lanzar corrección de movimiento y CNMF mediante CaImAn desde la interfaz;
no genera tracking de comportamiento.

Objetivo confirmado por la responsable (2026-10-27): que pueda utilizarlo
cualquier persona que trabaje en calcium imaging. La implementación actual
está centrada en Mini2P. La responsable confirma que primero hay que resolver
bien Mini2P; la compatibilidad con otros equipos queda para una fase posterior,
sin alcance definido ni validación todavía. No ampliar ahora los requisitos
para cubrir otras adquisiciones.

Orden de trabajo deseado:

1. Comprobar los timestamps.
2. Alinear el tracking.
3. Definir y discutir el análisis posterior, con CaImAn como referencia inicial.

Decisión confirmada: integrar CaImAn como motor de procesamiento de fondo de
CALI para corregir movimiento y extraer componentes mediante CNMF, con
sus resultados accesibles desde la aplicación. Usar CaImAn como biblioteca o
proceso de cálculo; no reimplementar sus algoritmos. La primera integración
está implementada mediante QProcess y una ventana de configuración simplificada.
El alcance y la configuración del pipeline
y de los análisis posteriores deben concretarse; el análisis de movimiento
existente no se considera por ello una solución definitiva.

Entrada real confirmada: TIFF Mini2P originales que salen directamente de
ScanImage. No dar por hecha una corrección de movimiento previa. Requisito
confirmado: admitir un canal o varios, sin fijar el lector a una configuración
de adquisición particular; esto no cambia la prioridad inicial Mini2P.
Número de planos, organización de páginas, archivos por sesión y metadatos
de adquisición siguen pendientes de inspección o confirmación. No asumir
que cada página TIFF equivale a un frame de calcio de un solo plano/canal.
La responsable no dispone ahora de una grabación de ejemplo. Se buscarán datos
públicos; no volver a pedirle una grabación como requisito para avanzar.

### Datos públicos localizados para pruebas (2026-10-27)

- CaImAn `example_movies/demoMovie.tif` (18,6 MB según GitHub):
  https://github.com/flatironinstitute/CaImAn/blob/main/example_movies/demoMovie.tif
  Candidato para probar el procesamiento, ya usado por el generador de demo
  del proyecto. No acredita compatibilidad con Mini2P/ScanImage multicanal.
- Ejemplos reales de ScanImage de NeuroConv/RoiExtractors:
  https://gin.g-node.org/CatalystNeuro/ophys_testing_data
  Procedencia documentada en
  https://neuroconv.readthedocs.io/en/stable/developer_guide/testing_suite.html
  y ejemplos de lectura en
  https://neuroconv.readthedocs.io/en/main/conversion_examples_gallery/imaging/scanimage.html
  La documentación contempla multicanal y varios archivos. La búsqueda no
  pudo abrir el listado GIN: falta confirmar archivos concretos, tamaños,
  contenido y acceso antes de declarar validado un caso multicanal.
- M-MINI2P, datos de los autores en Dryad:
  https://doi.org/10.5061/dryad.kd51c5bkp
  TIFF de calcio de microscopía miniaturizada; paquetes de calcio de 4,44,
  7,57 y 15,25 GB. Parte está demultiplexada por campo de visión/profundidad.
  No confundir varios FOV o planos con canales de fluorescencia, ni asumir que
  son TIFF originales ScanImage. Inspeccionar antes de usarlos como validación
  del lector. El paquete de 430 MB es de voltaje, no de calcio.

Se ha descargado `demoMovie.tif` en `/private/tmp/minisync-demoMovie.tif` para
validar el procesamiento. SHA-256:
`6f1dca4ac3329cded72c6f3ac90a725be32265db16cc6f681b522a2dd825682b`.
Los otros datos todavía no se han descargado. Registrar procedencia, licencia y transformaciones al preparar
fixtures. Las pruebas sintéticas multicanal pueden complementar las reales,
pero no sustituyen validar un archivo ScanImage auténtico multicanal.

Paquete local solicitado para pruebas: `datos_prueba_minisync/`, excluido de
Git mediante `.gitignore`. Contiene TIFF original de la demo (2.000 frames),
vídeo de conducta SIMULADO (3.030 frames), ambos CSV TTL SIMULADOS, guía
`LEEME.md`, configuración del worker, procedencia, hashes y carpeta `resultados/`.
No contiene tracking ni resultados CNMF precalculados. Puede regenerarse con
`scripts/create_processing_test_pack.py --source /ruta/demoMovie.tif --output /ruta/carpeta_nueva`.
El vídeo no es una grabación real de un animal; no hay asociación biológica
con el calcio. TIFF solo basta para procesar; para visualización sincronizada
se usan además vídeo y ambos CSV TTL; tracking solo para sus análisis específicos.

El problema de los timestamps se ha dejado pendiente. La conversación ha
avanzado de la revisión de funciones a definir la integración de CaImAn.
No interpretar el orden
de trabajo anterior como autorización para empezar a corregir timestamps ahora.

La interfaz y el README están actualmente en inglés. La conversación de esta
revisión es en español; la lengua deseada para futuras modificaciones de la
interfaz está pendiente de confirmar.

## Mapa del código

| Fichero | Responsabilidad |
| --- | --- |
| `sync_viewer.py` | Punto de entrada, ventana `Viewer`, carga y reconstrucción TTL, navegación, imágenes, tema visual, recortes y exportaciones; contiene también `TrackingAlignmentDialog`. |
| `caiman_results.py` | `CaImAnResults`: lector HDF5 sin importar CaImAn, validación de matrices, calidad de componentes, trazas, footprints y correspondencia de muestras con frames Mini2P. |
| `calcium_pipeline.py` | Worker/CLI sin Qt: validación de TIFF, separación de canal, corrección de movimiento, CNMF, deconvolución, calidad, ΔF/F y procedencia. Importa CaImAn solo al ejecutar el cálculo. |
| `processing_dialog.py` | `CalciumProcessingDialog`: reutiliza TIFF cargado, controles básicos/avanzados, detección interna del motor, QProcess, trabajos por canal y carga automática en el visor. |
| `environment-caiman.yml` | Entorno opcional del motor, separado de la interfaz: Python 3.11, CaImAn 1.12.1, setuptools<81 y scipy<1.17. |
| `movement_analysis.py` | Cálculo numérico separado de Qt: velocidad, segmentos válidos, interpolación, pesos temporales, resumen por célula y correlación con desfase. |
| `movement_dialog.py` | `MovementAnalysisDialog`: configuración, tabla por célula, gráficos, selección de ROI, invalidación de resultados y exportación. Recibe la clase de tracking como factoría para reutilizar su lector y mapeo. |
| `scripts/create_caiman_demo.py` | Generador de una demostración con ajuste CNMF real y datos auxiliares simulados. Requiere un entorno CaImAn independiente. |
| `tests/` | Pruebas `unittest` con datos sintéticos y pruebas de flujo Qt y exportaciones. |
| `mini2p_logo_mark.png`, `icons/` | Recursos visuales locales. |
| `README.md` | Instrucciones de arranque y descripción detallada de CaImAn y movimiento. |

No hay empaquetado de aplicación, servidor, base de datos, configuración de CI
ni archivo de bloqueo de dependencias en el árbol revisado. El estado de la
sesión vive en memoria; no se ha encontrado guardado/restauración de sesiones.
La navegación es manual mediante cursor, clics y controles de frames.

## Arranque y entorno

Dependencias de `requirements.txt`: PySide6, pyqtgraph, opencv-python, tifffile,
pandas, numpy y h5py, sin versiones fijadas.

```bash
python -m pip install -r requirements.txt
python sync_viewer.py
```

Ejecutar desde un entorno que contenga esas dependencias. No dar por supuesto
que `python`, `python3` y el intérprete de Conda son equivalentes.

Entorno observado durante esta revisión, sin establecerlo como requisito:

- Equipo macOS; repositorio en `/Users/lorena/Developer/mini2p_sync_viewer`.
- `python3`: Python 3.13.2 de Homebrew, sin numpy ni h5py.
- `/Users/lorena/miniconda3/bin/python`: Python 3.11.5; ninguna de las siete
  dependencias detectada; directorio de entornos Conda vacío.
- No se ha identificado aún el entorno habitual de ejecución ni la ubicación
  de las grabaciones o de la demostración preparada.

**Entorno habitual confirmado después por la responsable y localizado:**
`mini2p-sync` (guion, no subrayado) en la instalación Conda de Homebrew.
Usar este entorno en futuras sesiones; la inspección inicial anterior solo
cubrió otra instalación de Conda y no describe la instalación activa.

- Interfaz: `/opt/homebrew/Caskroom/miniconda/base/envs/mini2p-sync/bin/python`
  (Python 3.11.17 ARM64, PySide6 6.11.2, pyqtgraph 0.14.0, NumPy 2.4.6,
  tifffile 2026.3.3, pandas 3.0.6 y h5py 3.16.0).
- Motor ya existente: `/opt/homebrew/Caskroom/miniconda/base/envs/caiman/bin/python`
  (Python 3.11.12 ARM64, CaImAn 1.12.1, SciPy 1.15.2, NumPy 1.26.4,
  setuptools 80.1.0). No se han cambiado paquetes de estos entornos existentes.
- Arranque habitual: `conda activate mini2p-sync` y `python sync_viewer.py`.
- El diálogo detecta el entorno hermano `caiman` como Python del motor, si
  existe; no muestra la ruta ni un selector de Python. También reconoce el
  hermano `cali-caiman` (y el antiguo `minisync-caiman`) y la variable
  `CALI_CAIMAN_PYTHON` (y la antigua `MINISYNC_CAIMAN_PYTHON`) para despliegue.
  No importar CaImAn dentro de Qt.

Durante la implementación se han creado entornos **temporales de validación**:
`/private/tmp/minisync-viewer-env` (Python 3.13, dependencias de requirements)
y `/private/tmp/minisync-caiman-env` (Python 3.11 Intel/Rosetta, CaImAn 1.12.1).
No asumir que sobrevivirán a la limpieza del sistema ni que son el entorno
habitual de la responsable. El Python del motor se resuelve en la lógica interna.

Compatibilidad detectada en ejecución: CaImAn 1.12.1 importa `pkg_resources`
(requiere setuptools<81) y su deconvolución falla con el Toeplitz por lotes de
SciPy 1.17 (usar scipy<1.17; validación con 1.16.3). No arreglarlo modificando
los algoritmos de CaImAn ni quitando la deconvolución silenciosamente.

## Entradas y convenciones temporales

### TTL y reloj común

- Ambos CSV TTL requieren `frame` y `timestamp_ms`. Pueden contener columnas
  adicionales, como `elapsed_ms`.
- `load_csv` convierte los frames a enteros y los tiempos a flotantes; rechaza
  tablas vacías y tiempos decrecientes. No valida exhaustivamente finitud,
  unicidad de tiempos o integridad de IDs antes de convertirlos. Algunas
  funciones posteriores exigen tiempos estrictamente crecientes.
- `Viewer.rebuild()` establece `t0` en el primer `timestamp_ms` Mini2P y resta
  **ese mismo origen** a ambas series. El eje principal está en milisegundos.
  La cámara puede empezar en tiempo relativo negativo.
- La responsable confirma que ambos CSV TTL los registra el mismo
  Arduino/dispositivo. El código presupone timestamps comparables en un reloj
  común; no estima desfases entre relojes independientes ni corrige deriva.
  Modelo de hardware, firmware, unidades de origen y posibles reinicios o
  desbordamientos del contador siguen pendientes de confirmar.

### Reconstrucción de cámara y correspondencia con vídeo

- `median_period` toma la mediana de los intervalos positivos.
- `virtual_camera_indices` estima saltos con
  `max(1, round(intervalo / periodo_mediano))` y los acumula desde cero.
- `load_camera` llama siempre a `fill_camera_timestamps`: si detecta saltos,
  inserta filas entre los TTL registrados, interpola sus tiempos entre los
  extremos medidos y reconstruye IDs consecutivos desde el primer `frame`.
  Si existe `elapsed_ms`, lo recalcula respecto al primer TTL de cámara.
  Otras columnas añadidas en las filas nuevas pueden quedar vacías.
- No añade tiempos antes del primer TTL ni después del último. Conserva
  tiempos de los extremos medidos; los tiempos insertados son estimaciones.
  No hay una columna explícita que marque cada fila como medida o reconstruida.
- Esta operación sucede **antes** de seleccionar el modo de mapeo. Ambos modos
  trabajan sobre el CSV ya procesado; `TTL index` no recupera las filas crudas.
- Índice de vídeo interno, base cero:
  - `Timing reconstruction`: `offset + camera_virtual[índice TTL]`.
  - `TTL index`: `offset + índice TTL`.
- Offset por defecto: cero; permite valores negativos y positivos. No es un
  desplazamiento temporal en milisegundos, sino un desplazamiento en frames.
- La hipótesis de reconstrucción es que faltan registros TTL de una cámara
  aproximadamente periódica. No demuestra por sí sola que existan todos los
  frames correspondientes en el vídeo. Validarlo con adquisición real.
- Los gaps se detectan por intervalo mayor que 1,5 veces el periodo mediano,
  sobre las series de trabajo; la reconstrucción puede eliminar gaps visibles.

### Imágenes y navegación

- Mini2P `frame` se usa como ID base uno: página TIFF = `frame - 1`.
  Se abre un TIFF multipágina por vez; no hay ensamblado de varios archivos.
- Vídeo leído por OpenCV, TIFF por tifffile; cachés LRU de 80 y 40 frames.
- Para el tiempo elegido, cada visor selecciona el TTL más cercano mediante
  `nearest`. Puede mostrar un extremo aunque el cursor esté fuera de cobertura;
  esto no equivale a la política de cobertura de los análisis.
- Flechas izquierda/derecha: frame Mini2P anterior/siguiente.
  PageUp/PageDown: gap de cámara anterior/siguiente.
- Las imágenes se adaptan al panel; la representación en gris usa `gray8`.
  Las transformaciones de visualización no redefinen las señales CaImAn.

## Tracking

`TrackingAlignmentDialog` acepta CSV plano y CSV DeepLabCut de tres cabeceras.
En DLC combina las etiquetas de parte corporal/coordenada y conserva el índice
original como `frame_index`.

- `frame_index`, `frame_idx`, `index` y `Unnamed: 0` se interpretan en base cero.
- `frame`, `frame_number` y `frame_id` se interpretan en base uno, salvo que
  aparezca un cero explícito, que identifica base cero.
- Índices finitos, enteros, únicos y crecientes. Con vídeo, deben caber en él.
  Sin columna de frames, asigna filas consecutivas; con vídeo exige igual
  número de filas y frames.
- `build_video_times` aplica modo y offset; interpola tiempos entre TTL
  cubiertos, respeta el corte y deja NaN fuera de los extremos disponibles.
- La ventana alinea **una columna numérica** seleccionada, normalmente X.
  Ofrece tiempos de cámara o una fila por frame Mini2P.
- Interpola linealmente posiciones dentro de los límites configurados de
  huecos; no extrapola. Por defecto permite dos frames ausentes. La política
  de huecos de este diálogo es distinta de la del análisis de movimiento.
- En modo Mini2P conserva las filas de la serie completa; posiciones fuera
  del corte/cobertura quedan vacías.
- Exporta CSV con vecinos de interpolación, alpha, frame real de vídeo más
  cercano y diferencia temporal. El vídeo alineado usa ese frame más cercano;
  repite frames cuando corresponde y escribe imágenes vacías sin cobertura.
- El MP4 alineado tiene FPS constante estimado por la mediana de intervalos
  objetivo; los tiempos exactos se conservan en el CSV `.mapping.csv` asociado.

## CaImAn

### Procesamiento implementado

- Botón `Calcium analysis` en Timeline, junto a Align tracking y Movement analysis;
  no en Files. No necesita TTL para calcular; la
  sincronización posterior sigue necesitando los TTL reales.
- Reutiliza el TIFF abierto en el visor (usar `tif.filehandle.path`, ya que
  `tif.filename` devuelve solo el nombre). Add TIFF añade archivos; la papelera
  limpia la selección, sin eliminar archivos del disco. No hay lista blanca
  de rutas ni botones de reordenar/eliminar con texto.
- Interfaz básica: Frame rate (Hz), Channels y Planes, More options y Run analysis.
  Mantenerla simple por petición explícita de la responsable: sin introducción,
  pestañas de configuración/before-after, información técnica del archivo,
  rutas de Python ni panel visible de logs/pasos.
- Se etiqueta Frame rate, no Firing rate: es frecuencia de adquisición por canal,
  no descarga neuronal. Prefiere metadatos ScanImage, luego la mediana de los
  intervalos TTL Mini2P; es editable, y sin esos datos queda vacía para introducirla.
- Procesa un canal o Both channels como trabajos secuenciales independientes.
  Admite varios TIFF con dimensiones/layout compatibles y ciclos completos.
  Guarda automáticamente junto al TIFF en `cali_results/calcium_*` (antes
  `minisync_results/`); ambos
  canales generan subcarpetas y `batch.json`. Solo abre resultados al completar
  todos los trabajos; fallo/cancelación detiene la secuencia y conserva parciales.
- Detecta canales guardados de ScanImage o eje C explícito; sin metadatos, pide
  número de canales intercalados. Planes es un desplegable con 1 disponible y
  los demás deshabilitados: el motor todavía no soporta volumen/flyback.
- Rechaza planos múltiples conocidos, flyback, RGB y ejes incompatibles. Una
  pila 3D ambigua ZYX (como la demo ImageJ de CaImAn) se interpreta según
  la selección de un plano. No declarar soporte
  volumétrico ni multicanal real validado sin un archivo auténtico.
- CaImAn corrige movimiento rígido o por parches, inicializa CNMF por parches
  con p=0 y refina con AR(1), evalúa calidad sin CNN y calcula ΔF/F.
- Un worker sin interfaz, con límites de un hilo nativo y sin clúster externo;
  no bloquear Qt con llamadas síncronas de cálculo. Cancelación con terminate
  y kill diferido; impide cerrar la aplicación mientras el cálculo está activo.
- Cada ejecución crea una carpeta nueva; conserva los originales. Guarda
  TIFF del canal seleccionado y TIFF corregido usado para CNMF, HDF5,
  desplazamientos, mapping de cada muestra a TIFF/página/canal/frame Mini2P,
  hashes de origen, parámetros resueltos y estado. Mantiene mapas intermedios;
  prever espacio para varias copias float32. Fallos/cancelación conservan parciales.
- Carga automáticamente en el visor el TIFF corregido y el primer frame
  configurado (`tiff_first_frame`), cierra la ventana de configuración y activa
  Calcium en la pantalla principal. ROI, señal, canal, Play y controles de frame
  están en esa pantalla; no obligar a volver al diálogo para ver los resultados.
  Al procesar ambos canales ofrece un selector de canal en Calcium. La relación
  con IDs TTL la declara el usuario, no se deriva del número de páginas.
- Los resultados procesados se muestran completos por Movie frame (base uno),
  incluso sin TTL o con cobertura parcial. Play/slider/campo de frame/cursor
  seleccionan la misma muestra y página corregida; las ROI y señales se mantienen.
  Solo se sincroniza conducta si existe un tiempo TTL medido para esa muestra;
  fuera de cobertura se vacía el visor de conducta, sin inventar tiempos. El eje
  Movie frame no se enlaza con el eje Arduino en ms de la pestaña Timing.
- Si Accepted está vacío, iniciar en All components y explicar que ninguno
  pasó calidad. No modificar las etiquetas guardadas ni llamar aceptados a esos
  candidatos. Evitar una pantalla vacía solo por el filtro inicial.
- CaImAn HDF5 también permite reabrir processing.json/batch.json; al seleccionar
  HDF5 con manifest asociado carga el TIFF corregido, no solo las trazas.
- Exportación del resultado procesado: todas las muestras, tiempos TTL medidos
  cuando existen y NaN fuera de cobertura; el corte limita las filas exportadas.
  La reproducción es una vista previa a la frecuencia configurada, limitada a
  60 fps. El motor rechaza frecuencias fuera de 0.001–1000 Hz.
- Por ahora no transfiere desplazamientos de un canal estructural a otro
  funcional; cada canal elegido se procesa independientemente.

### Lectura de resultados

- Acepta `.h5`/`.hdf5` guardados con `cnm.save(...)`; requiere `estimates/C`,
  matriz componentes × muestras. No admite NWB ni pickle.
- Lee filas de trazas y columnas espaciales seleccionadas mediante h5py.
  No necesita instalar CaImAn para consultar resultados.
- Señales: `C`, `C+YrA`, `F_dff`, `S`, según presencia. No recalcula
  normalización o deconvolución. `C` es señal denoised; `S` es actividad
  deconvolucionada, no un registro de spikes medidos.
- IDs de componentes y muestras CaImAn en base cero, incluso tras filtrar
  aceptados/rechazados. Ausencia de evaluación no equivale a rechazo.
- Muestra CaImAn = `mini2p_frame - first_mini2p_frame`, con primer frame
  configurado en base uno y valor inicial 1. Sin interpolación de calcio;
  fuera de cobertura queda NaN. No resuelve downsampling, reordenación ni
  concatenación temporal mediante ese único parámetro.
- Footprints `A`: densos o CSC, píxeles × componentes, reshape Fortran.
  Dimensiones espaciales 2D opcionales; se pueden consultar solo las trazas.
- ROI dibujada al 20 % del máximo. Exigir dimensiones coincidentes no garantiza
  registro espacial: debe corresponder al mismo campo y sistema de coordenadas.
- Sin frame TIFF muestra `Cn` o footprint como referencia estática etiquetada.
- Exportación de traza aplica el corte temporal y conserva IDs y tiempo relativo.

## Movimiento y actividad

Requiere ambos CSV TTL, CaImAn y tracking referido al vídeo de comportamiento
original que corresponde al mapeo cargado. No usar como entrada un tracking ya
remuestreado a Mini2P. Puede trabajar sin vídeo; usar índices explícitos para
evitar ambigüedad. Reutiliza el tracking del diálogo de alineación si estaba
abierto al crear por primera vez la ventana de movimiento.

- Velocidad desde X/Y del mismo punto corporal, con `np.gradient` respecto a
  tiempos medidos en segundos, o desde una columna de velocidad no negativa.
- Unidades seleccionadas describen el archivo; no calibran ni convierten px.
- Filtrado por confianza opcional, mediana temporal configurable y límite de
  intervalo entre frames. Suavizado cero desactiva el filtro.
- NaN, baja confianza, frames saltados y tiempos excesivos separan segmentos;
  no interpolar velocidad a través de esos huecos ni fuera de cobertura.
- Velocidad >= umbral: movimiento; inferior: reposo. Sin cobertura: desconocido.
- Aplica primer frame CaImAn y corte temporal. Medias por estado ponderadas
  por duración observada: cada intervalo adyacente válido aporta la mitad a
  cada extremo, sin añadir duración en extremos ni entre segmentos.
- Pearson usa muestras finitas emparejadas, sin ponderación temporal. Menos
  de tres pares o señal constante produce NaN. Sin ambos estados, la diferencia
  de medias es indefinida. Son estadísticas descriptivas, sin p-valores.
- Desfase positivo: `calcium(t)` frente a `speed(t - lag)`; el calcio sigue al
  movimiento. La cobertura puede variar entre desfases. Es exploratorio.
- Seleccionar una fila enfoca esa ROI en el visor. Clics en gráficos temporales
  sincronizan los visores; los ejes del diálogo muestran segundos.
- Cambiar parámetros/fuentes/mapeo/corte invalida resultados y bloquea su
  exportación hasta recalcular. Un contador de generación impide aceptar
  resultados obsoletos si cambian parámetros durante el cálculo.
- Exporta carpeta nueva `movement_*` con `per_cell_summary.csv`,
  `aligned_movement.csv`, `roi_<id>_aligned.csv`, `roi_<id>_lag.csv` y
  `analysis_settings.json` con procedencia y parámetros.

## Recortes y exportaciones

- Corte temporal: final seleccionado por TTL de cámara; automático hasta el
  último TTL de cámara no posterior al último Mini2P. No es un recorte de inicio.
- Exportar corte crea `trimmed_*` con `camera_trimmed.csv`,
  `behavior_trimmed.mp4`, `trim_info.json`. Conserva el prefijo del vídeo hasta
  el frame mapeado; el CSV procede de la tabla de cámara ya reconstruida.
- Recorte espacial rectangular sobre vídeo: coordenadas originales, dimensiones
  pares para codificación. Exporta `cropped_*` con `behavior_cropped.mp4` y
  `crop_info.json`. También se aplica a exportación temporal o vídeo alineado.
- Exportaciones de vídeo usan OpenCV y códec `mp4v`; no conservan audio.
  No sustituyen los originales por diseño. No hay transacción general que
  revierta todos los archivos si una exportación falla; comprobar salidas.

## Validación y límites de lo comprobado

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Cobertura existente: reconstrucción TTL y jitter; tracking y DLC, índices,
huecos, corte y vídeo alineado; lectura HDF5, orientación de ROI, tipos de
señal y cursor; velocidad, duración, confianza, desfases, invalidación y
exportación de movimiento. Las pruebas crean fixtures temporales.

La revisión inicial con el Python de sistema falló por dependencias ausentes.
Tras crear el entorno de interfaz, se han ejecutado las pruebas incluyendo
fallo de motor y cancelación de un proceso real. La ventana de procesamiento
se ha renderizado e inspeccionado en Qt offscreen. Los detalles de validación
están en `docs/processing-validation.md`: demo real de 2.000 frames con
corrección rígida (12 componentes candidatos), y flujo QProcess multicanal
sintético/multifichero con corrección por parches (300 frames, 9 candidatos).
Ambos completaron CNMF y cargaron resultados compatibles. No equivale a
validación de un TIFF ScanImage multicanal auténtico ni de identidades celulares.
Con el entorno habitual `mini2p-sync`, antes de simplificar: 64 pruebas correctas, salida 0 y sin
avisos de destrucción de QObject. Los entornos temporales de prueba presentaron
problemas intermitentes de cierre Qt (también con pruebas anteriores); no
usarlos como referencia en lugar del entorno habitual. Se comprobó además
apertura/carga/cierre mediante el bucle QApplication normal en el entorno
habitual, con salida 0; los detalles y límites de los scripts de prueba están
en el informe.

Tras simplificar la interfaz: suite ampliada a 66 pruebas, con reutilización
del TIFF/rate TTL y secuencia Both channels. Prueba real con Qt/QProcess y
dos canales sintéticos de 300 muestras completó ambos CNMF (10 candidatos
por canal), carga automática y cambio de canal, con salida 0.

El README declara validación anterior con CaImAn 1.12.1 sobre `demoMovie.tif`
(2.000 frames, 15 componentes); no se reprodujo aquí. El script genera un CNMF
real, pero relojes TTL, vídeo de comportamiento y tracking son simulados,
sin relación biológica con el calcio. Su reloj de 20 Hz es una hipótesis de
demostración, no la frecuencia documentada de la adquisición original.
La sincronización con relojes de adquisición reales sigue pendiente según
el README. El generador requiere `--source` y `--output` nuevo, no existente.

## Criterios para futuras modificaciones

- Distinguir hechos del código, validaciones realizadas y decisiones todavía
  pendientes. No convertir hipótesis de la demo en hechos del experimento.
- Mantener explícitas bases de índices, unidades, tiempos medidos/reconstruidos
  y cobertura. Evitar rellenar actividad ausente con cero o llamar reposo a
  tracking desconocido.
- Al cambiar sincronización, revisar sus efectos en visor, tracking, CaImAn,
  movimiento, recortes e información de procedencia exportada.
- Preservar cambios locales ajenos. En la revisión inicial solo README,
  requirements y sync_viewer estaban en Git; los módulos CaImAn/movimiento,
  tests, scripts y recursos estaban sin seguimiento. No eliminarlos por ello.
- No añadir datos experimentales, resultados pesados o entornos al repositorio
  sin una decisión expresa. No hacer commits/publicaciones por esta revisión.
- Posibles mejoras detectadas, no tareas ya autorizadas: validar entradas TTL
  con más rigor, distinguir filas TTL reconstruidas, aclarar los dos modos tras
  reconstrucción y hacer reproducible el entorno.

## Información pendiente de la responsable

1. Experimento y objetivo científico concretos; funciones utilizadas con datos
   reales frente a funciones todavía experimentales. El público general y el
   orden timestamps → tracking → análisis ya están confirmados arriba.
2. Hardware/firmware del Arduino/dispositivo compartido, generación de CSV,
   pérdidas habituales (TTL, frames de vídeo o ambos), posibles reinicios o
   desbordamientos y método para determinar offset.
3. Entorno de ejecución habitual y ubicación de datos de prueba autorizados.
4. TIFF originales de ScanImage, soporte de uno/varios canales y ausencia de
   ejemplo propio ya confirmados: concretar planos,
   dimensiones, archivos por sesión, metadatos y correspondencia con TTL;
   inspeccionar una adquisición real antes de definir la preparación del pipeline.
5. Herramienta/formato de tracking, punto corporal y calibración de unidades;
   cómo se eligen confianza, umbral de movimiento y gap tolerado.
6. Prioridades próximas y preferencias de colaboración, idioma de interfaz,
   distribución a otros usuarios y estrategia de versiones.

Estas preguntas están pendientes; no asumir respuestas ni un roadmap aprobado.
