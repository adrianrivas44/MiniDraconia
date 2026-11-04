# MiniDraconia

Una pequeña compañera de escritorio para Windows: personaje animado, reacciones al tacto y frases guionizadas sin conexión. Basada en [DyberPet](https://github.com/ChaozhongLiu/DyberPet).

**Primer candidato comunitario: 1.0.0-rc.1. No es una versión estable.**

[English](README.md) · [Cómo colaborar](CONTRIBUTING.md) · [Alma y manual](docs/identity/README.md)

## Por qué la comparto

MiniDraconia empezó como un proyecto personal. Es mi primera publicación de software y la abro para aprender y construir con otras personas. Si tienes una idea, encuentras un error o sabes mejorar sus animaciones, diálogos, accesibilidad o código, tu aportación es bienvenida. No necesitas ser experto: probarla, traducir, sugerir y explicar también ayuda.

**Ayúdame a decidir qué sigue:** [comparte una idea o reporta un error](https://github.com/adrianrivas44/MiniDraconia/issues), crea tu fork y envía un pull request pequeño, o empieza por [la guía para colaborar](CONTRIBUTING.md). Se reciben aportaciones en español e inglés.

— Zero / [adrianrivas44](https://github.com/adrianrivas44)

## Qué funciona y qué no

La mascota se anima, responde a zonas de tacto y arrastre con frases inglesas predefinidas, tiene ajustes y permite salir desde su menú. Sus datos se guardan localmente, fuera de la carpeta de instalación. Los clips de voz tienen aprobación individual antes de poder reproducirse.

**Todavía no conversa con IA.** No incluye modelo local ni servidor de inferencia. Conectar un modelo propio de Claude o xAI forma parte del roadmap; no está implementado. Una suscripción de chat no equivale a acceso API. El alma describe su identidad conversacional; no instala modelos ni activa memoria, cámara, micrófono o herramientas.

## Abrirla en Windows

Descarga el ZIP de Windows de la [versión preliminar 1.0.0-rc.1](https://github.com/adrianrivas44/MiniDraconia/releases/tag/v1.0.0-rc.1), no el ZIP automático del código fuente. Es un candidato comunitario experimental, no una versión estable ni certificada. Extrae la carpeta completa y abre `MiniDraconia/MiniDraconia.exe`. No separes el ejecutable de `_internal`. El menú permite abrir Settings o Quit.

Objetivo inicial: Windows 11 x64. No se afirma compatibilidad probada con otros sistemas. No debería necesitar permisos de administrador. Si Windows muestra una advertencia de reputación de software sin firmar, revisa el origen y el checksum; no desactives el antivirus.

Lee las notas de la versión y compara su SHA256 antes de abrirla. El paquete público corresponde al snapshot fuente adjunto a esa misma versión, con los avisos verificados de Python/OpenSSL; la documentación comunitaria del repositorio puede ser posterior. La [lista de publicación](docs/RELEASE-CHECKLIST.md) distingue comprobaciones técnicas y limitaciones pendientes. Que esté disponible públicamente no significa que se hayan resuelto todas las preguntas de derechos o las revisiones humanas.

## Colaborar

Puedes ayudar con arranque y escalado en Windows, animación, caída y arrastre, accesibilidad, diálogos, pruebas y empaquetado. Consulta [CONTRIBUTING.md](CONTRIBUTING.md), [desarrollo](docs/DEVELOPMENT.md), [roadmap](docs/ROADMAP.md) y [limitaciones](docs/KNOWN-ISSUES.md).

Se incluyen el alma del producto y el manual visual para entenderla sin adivinar su personalidad ni cambiar su identidad por accidente. Draconia es un personaje adulto creado por fans e inspirado en Draco Malfoy, no oficial. Se conserva la licencia GPL-3.0 del motor y la atribución a Chaozhong Liu/DyberPet. Eso no concede derechos sobre personajes, marcas o material ajeno: [revisión de derechos](docs/RIGHTS-REVIEW.md).
