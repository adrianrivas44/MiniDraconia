# MiniDraconia

Una pequeña compañera de escritorio para Windows: camina, trepa los bordes de la pantalla en su escoba, reacciona al tacto y conversa con frases sin conexión o con tu propia IA si la conectas. Basada en [DyberPet](https://github.com/ChaozhongLiu/DyberPet).

**Candidato 1.0.0-rc.3, la versión preliminar más reciente. Experimental, no es una versión estable.**

[English](README.md) · [Cómo colaborar](CONTRIBUTING.md) · [Alma y manual](docs/identity/README.md) · [Conecta tu propia IA](docs/CONNECT-YOUR-AI.md) · [Recomendaciones y pruebas](docs/RECOMMENDED-SETUP.md) (en inglés, con resumen en español)

## Por qué la comparto

MiniDraconia empezó como un proyecto personal. Es mi primera publicación de software y la abro para aprender y construir con otras personas. Si tienes una idea, encuentras un error o sabes mejorar sus animaciones, diálogos, accesibilidad o código, tu aportación es bienvenida. No necesitas ser experto: probarla, traducir, sugerir y explicar también ayuda.

**Ayúdame a decidir qué sigue:** [comparte una idea o reporta un error](https://github.com/adrianrivas44/MiniDraconia/issues), crea tu fork y envía un pull request pequeño, o empieza por [la guía para colaborar](CONTRIBUTING.md). Se reciben aportaciones en español e inglés.

— Zero / [adrianrivas44](https://github.com/adrianrivas44)

## Qué funciona y qué no

La mascota se ve nítida con el escalado de la pantalla, camina de verdad por la pantalla (y mira hacia dónde va), sigue al cursor, trepa los bordes en su escoba, se sienta, lee y toma té. Nuevo en 1.0.0-rc.3: un servidor de modelos en tu propio equipo funciona igual de rápido con `localhost` que con `127.0.0.1`, tiene tiempo para cargar el modelo (la app lo calienta en segundo plano y ella se queda pensando mientras llega una respuesta lenta) y los prefijos `assistant>` o las etiquetas de emoción rotas de los modelos pequeños ya no llegan a su globo. Desde 1.0.0-rc.2: tres animaciones propias (**mirror**, su espejo; **quill**, escribe en su libreta; y **yawn**, bosteza antes de dormirse) y su propio icono para el ejecutable, su ventana, la bandeja y Settings. Admite un paquete de voz opcional que cualquiera puede grabar para sus frases guardadas ([voice pack](docs/VOICE-PACK.md), en inglés); no se incluye ninguno. Responde a zonas de tacto y arrastre, y mueve la boca mientras dice una frase. Tiene ajustes y permite salir desde su menú. Sus datos se guardan localmente, fuera de la carpeta de instalación. Los clips de voz tienen aprobación individual antes de poder reproducirse.

No incluye modelo local ni servidor de inferencia. El alma describe su identidad; no activa memoria, cámara, micrófono ni herramientas.

## Hablar con Draconia

Tiene tres modos y nada viene preconfigurado: la descarga no apunta a ningún proveedor de IA.

- **Sin conexión (predeterminado).** Responde con sus frases en inglés incluidas. No se envía nada a ningún sitio y no hace falta cuenta.
- **Tu propia IA (opcional).** En *Settings → AI / Privacy → Connect your own AI*, escribe la URL base y el nombre del modelo de cualquier servicio compatible con OpenAI: un servicio que tú elijas (con tu clave API) o un servidor en tu propio equipo, como Ollama (`http://127.0.0.1:11434/v1`) o LM Studio (`http://127.0.0.1:1234/v1`), que no necesita clave. Los campos empiezan vacíos; *Test connection* hace una sola petición mínima. La clave nunca se envía por `http://` sin cifrar a otro equipo. Una suscripción de chat no es una clave API. Un servicio externo puede cobrar en tu cuenta: un límite diario (200 por defecto, editable) la detiene y, al pasarlo, responde sin conexión hasta el día siguiente. Guía: [conecta tu propia IA](docs/CONNECT-YOUR-AI.md).
- **Relay propio (avanzado).** Si mantienes tu propio servicio relay, un archivo `minidraconia_relay.json` junto al ejecutable conecta su chat escrito a él, con voz. La descarga no incluye ninguno. El protocolo exacto está en [self-hosted relay](docs/SELF-HOSTED-RELAY.md) (en inglés).
- **Qué gasta qué.** Caricias, pellizcos, toques, arrastrarla, dejarla caer, saludos, despedidas, comentarios al volver y su charla espontánea siempre usan sus frases guardadas en tu equipo, en cualquier modo: nunca envían nada ni gastan peticiones. Solo un mensaje que escribes en *Talk to Draconia* va a tu IA, y solo eso cuenta para el límite diario.
- **Qué se envía y a quién.** Solo con tu propia IA o un relay propio, solo cuando envías un mensaje escrito y solo a la dirección que configures: ese mensaje y la conversación escrita reciente (solo en memoria), con el prompt del personaje en el caso de tu propia IA. Nada más: ni eventos del escritorio, ni archivos, ni capturas, ni pulsaciones de teclado. Ese servicio puede conservar lo que recibe según sus propias condiciones.
- **Tu clave** se guarda cifrada en tu equipo con Windows (DPAPI, solo para tu usuario de Windows). Nunca se escribe en texto plano, ni se vuelve a mostrar, ni se registra. *Forget key* la borra.
- Si algo falla (sin conexión, clave rechazada, límite alcanzado), responde con sus frases sin conexión; el globo siempre funciona.

Más detalles en [privacidad](docs/PRIVACY.md) (en inglés).

## Abrirla en Windows

Descarga el ZIP de Windows de la [versión preliminar más reciente](https://github.com/adrianrivas44/MiniDraconia/releases) (1.0.0-rc.3), no el ZIP automático del código fuente. Es un candidato comunitario experimental, no una versión estable ni certificada. Extrae la carpeta completa y abre `MiniDraconia/MiniDraconia.exe`. No separes el ejecutable de `_internal`. El menú permite abrir Settings o Quit.

Objetivo inicial: Windows 11 x64. No se afirma compatibilidad probada con otros sistemas. No debería necesitar permisos de administrador. Si Windows muestra una advertencia de reputación de software sin firmar, revisa el origen y el checksum; no desactives el antivirus.

Lee las notas de la versión y compara su SHA256 antes de abrirla. El paquete público corresponde al snapshot fuente adjunto a esa misma versión, con los avisos verificados de Python/OpenSSL; la documentación comunitaria del repositorio puede ser posterior. La [lista de publicación](docs/RELEASE-CHECKLIST.md) distingue comprobaciones técnicas y limitaciones pendientes. Que esté disponible públicamente no significa que se hayan resuelto todas las preguntas de derechos o las revisiones humanas.

## Colaborar

Puedes ayudar con arranque y escalado en Windows, animación, caída y arrastre, accesibilidad, diálogos, pruebas y empaquetado. Consulta [CONTRIBUTING.md](CONTRIBUTING.md), [desarrollo](docs/DEVELOPMENT.md), [roadmap](docs/ROADMAP.md) y [limitaciones](docs/KNOWN-ISSUES.md).

Se incluyen el alma del producto y el manual visual para entenderla sin adivinar su personalidad ni cambiar su identidad por accidente. Draconia es un personaje adulto creado por fans e inspirado en Draco Malfoy, no oficial. Se conserva la licencia GPL-3.0 del motor y la atribución a Chaozhong Liu/DyberPet. Eso no concede derechos sobre personajes, marcas o material ajeno: [revisión de derechos](docs/RIGHTS-REVIEW.md).
