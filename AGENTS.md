# Instrucciones para trabajar en CALI

Mantener este archivo centrado en instrucciones y decisiones vigentes del
repositorio. Documentar procedimientos y validaciones detalladas en `docs/`;
no añadir transcripciones de sesiones, rutas personales ni inventarios del
ordenador de una persona.

## Alcance

CALI (CAlcium LInked Behavior explorer) es una aplicación local de escritorio
Python/Qt para inspeccionar y alinear imágenes Mini2P y vídeo de comportamiento
mediante CSV de pulsos TTL. Permite alinear tracking existente, consultar
resultados CaImAn y explorar asociaciones descriptivas entre calcio y movimiento.
No genera tracking.

- Priorizar Mini2P/ScanImage; la compatibilidad con otros equipos queda fuera
  del alcance actual. No ampliar requisitos sin una decisión explícita.
- Usar CaImAn para corrección de movimiento y CNMF; no reimplementar sus algoritmos.
- La interfaz y la documentación de usuario están en inglés. Conservar los
  nombres existentes salvo que la tarea solicite cambiarlos.
- El proyecto se llamaba MINISYNC. Conservar nombres y rutas de informes
  históricos y los alias de compatibilidad aún admitidos.
- La licencia de código y logos está pendiente de elección explícita.

## Entorno y validación

Usar el entorno de interfaz `cali`, definido en `environment.yml`, con Python
3.11 y las dependencias de `requirements-lock.txt`. No asumir que `python`,
`python3` y los intérpretes de distintos entornos son equivalentes.

```bash
conda activate cali
python cali.py
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

- CaImAn utiliza un entorno independiente; consultar `environment-caiman.yml`.
  CaImAn 1.12.1 requiere `setuptools<81` y `scipy<1.17`. No eludir problemas de
  compatibilidad modificando sus algoritmos o quitando la deconvolución.
- El diálogo resuelve internamente el motor mediante entornos hermanos o
  `CALI_CAIMAN_PYTHON`; conserva los alias antiguos admitidos. No importar
  CaImAn dentro de Qt ni ejecutar cálculo pesado síncrono en la interfaz.
- No modificar un entorno de trabajo existente solo para probar dependencias.
- Ejecutar las pruebas pertinentes y la suite completa para cambios de flujo.
  Revisar visualmente ambos temas para cambios de interfaz, también con datos
  cargados y al redimensionar. Offscreen no sustituye una comprobación interactiva.
- Registrar qué se probó y sus límites. Pasar la suite no acredita una ejecución
  CNMF completa, identidades celulares ni compatibilidad con ScanImage real multicanal.

Guía de desarrollo: [docs/development.md](docs/development.md).
Validaciones del motor: [docs/processing-validation.md](docs/processing-validation.md).

## Mapa del código

| Archivo | Responsabilidad |
| --- | --- |
| `cali.py` | Entrada, `Viewer`, TTL, navegación, imágenes, recortes, exportaciones y `TrackingAlignmentDialog`. |
| `theme_toggle.py` | Selector de tema y transición visual. |
| `caiman_results.py` | Lectura HDF5 con h5py, trazas, footprints, calidad y correspondencia de muestras. No requiere CaImAn. |
| `calcium_pipeline.py` | Worker/CLI sin Qt: TIFF, canales, corrección de movimiento, CNMF y procedencia. |
| `processing_dialog.py` | Configuración simplificada, QProcess, secuencia de canales y carga de resultados. |
| `movement_analysis.py` | Cálculo numérico sin Qt: velocidad, cobertura, duración y correlaciones. |
| `movement_dialog.py` | Configuración, gráficos, invalidación y exportaciones de movimiento. |
| `tests/` | unittest con fixtures temporales y pruebas de flujo Qt. |
| `scripts/` | Generadores de demos y datos auxiliares de prueba. |
| `icons/` | Recursos visuales y logos. |

## Convenciones científicas y de datos

- CSV TTL: columnas `frame` y `timestamp_ms`. Ambas adquisiciones usan un reloj
  común; el origen relativo es el primer timestamp Mini2P para las dos series.
  No inferir desfases entre relojes independientes ni corregir deriva implícitamente.
- La carga de cámara reconstruye registros TTL ausentes antes de aplicar el modo
  de mapeo. Los tiempos interpolados son estimaciones; no demuestran que existan
  todos los frames en el vídeo. `TTL index` tampoco recupera la tabla cruda.
- El offset de vídeo está en frames, no en milisegundos. Los índices internos de
  vídeo y CaImAn son base cero; los IDs Mini2P y Movie frame se muestran en base uno.
- El visor TIFF original utiliza página = `frame - 1`. No generalizar esa
  correspondencia al procesamiento multicanal ni asumir que cada página ScanImage
  representa una muestra de un único plano/canal.
- Mantener explícitos unidades, bases de índices, cobertura y tiempos medidos o
  reconstruidos. No rellenar actividad ausente con cero ni llamar reposo al
  tracking desconocido. No extrapolar fuera de cobertura.
- Al cambiar sincronización, revisar visor, tracking, calcio, movimiento,
  recortes y procedencia exportada. Las mejoras de timestamps pendientes no
  son una tarea implícita en otros cambios.
- El tracking se refiere al vídeo original. Conservar las convenciones de base
  cero/uno de su lector y las políticas de huecos propias de cada análisis.
- Movimiento y calcio producen estadísticas descriptivas, no evidencia causal.
  `S` es actividad deconvolucionada, no spikes medidos. Desfase positivo compara
  `calcium(t)` con `speed(t - lag)`. Invalidar resultados cuando cambien entradas,
  parámetros, mapeo o corte; no permitir exportar resultados obsoletos.

Detalles: [sincronización y tracking](docs/synchronization.md),
[resultados de calcio](docs/calcium-results.md) y
[análisis de movimiento](docs/movement-analysis.md).

## Procesamiento y resultados

- Las entradas son TIFF originales de ScanImage; no presuponer corrección previa.
  El motor admite un plano y canales independientes; rechazar volumen/flyback,
  RGB y layouts incompatibles. No declarar validado un TIFF ScanImage multicanal
  auténtico basándose solo en fixtures sintéticos o la demo de CaImAn.
- Mantener la configuración básica simple: Frame rate (Hz), Channels, Planes,
  More options y Run analysis. Frame rate es frecuencia de adquisición por canal,
  no frecuencia de descarga neuronal. No exponer rutas de Python ni un panel de logs.
- Procesar ambos canales como trabajos secuenciales independientes. Conservar
  originales, crear una carpeta nueva por ejecución y conservar parciales ante
  fallo/cancelación. Mantener manifests, parámetros, hashes y mapping de muestras.
- Al completar, abrir el TIFF corregido y resultados en el visor principal.
  `.h5`/`.hdf5` y los manifests asociados deben seguir permitiendo reabrir resultados.
- Mostrar todas las muestras procesadas por Movie frame, incluso sin TTL. Solo
  sincronizar conducta donde exista un tiempo TTL medido; vaciarla fuera de
  cobertura. No enlazar Movie frame con el eje Arduino en ms.
- Si no hay componentes aceptados, mostrar candidatos mediante All components
  y explicar el resultado de calidad. No alterar etiquetas ni llamar aceptados
  a los candidatos. Conservar avisos de incompatibilidad o selección vacía.
- Mantener exportaciones con IDs, unidades, cobertura y procedencia. Los tiempos
  sin cobertura son NaN; los vídeos de FPS constante conservan tiempos exactos
  en el CSV de mapping. No sustituir los originales.

Flujo detallado: [docs/calcium-processing.md](docs/calcium-processing.md).

## Interfaz

- Usar los logos horizontales claro/oscuro de `icons/logo/`. Acentos de CALI:
  violeta/magenta de día y amarillo/melocotón de noche. Mantener oscuros todos
  los fondos nocturnos, incluidos controles deshabilitados y diálogos.
- La barra lateral contiene Load Files y Load Processed Data, con botones en
  columna. Debajo, Tracking contiene Align tracking; Analysis contiene Movement
  analysis y Calcium analysis. Estas acciones no pertenecen a la cabecera Timeline.
- Conservar las pestañas con aspecto de carpeta y su estilo común en ambos temas.
- Los títulos y controles de cámara están fuera de las tarjetas de imagen.
  Crop, Reset y Export van junto a Behavior camera, a la altura del selector de
  tema situado a la derecha de la cabecera Mini2P. Separar ambos visores por 14 px.
- Las imágenes ocupan su tarjeta conservando proporciones. Su pixmap no debe
  determinar el tamaño mínimo del layout ni disparar recálculos de altura por
  cada frame. Comprobar estabilidad con ambas imágenes cargadas.
- Timeline comienza a la altura del borde superior de Navigate cuando hay
  espacio; reservar altura suficiente para los controles en ventanas pequeñas
  y en la pestaña Calcium. La barra lateral admite desplazamiento vertical.
- Mantener accesibilidad, navegación por teclado y avisos útiles. No reintroducir
  el resumen rutinario de componentes, frames, Full movie y cobertura TTL.

## Cambios y datos de prueba

- Preservar cambios locales ajenos, incluidos archivos sin seguimiento.
- No hacer commits, push, publicaciones o cambios en GitHub sin autorización.
- No versionar cachés, `.DS_Store`, entornos, grabaciones experimentales ni
  resultados pesados. No borrar archivos locales para dejar de versionarlos.
- Registrar procedencia, licencia y transformaciones de fixtures. Las demos
  pueden combinar calcio real con vídeo, TTL y tracking simulados; no presentar
  esa combinación como una asociación biológica o una sincronización real validada.
- No exigir una grabación propia para avanzar: usar datos públicos adecuados o
  fixtures sintéticos, explicando qué validan y qué queda sin comprobar.
