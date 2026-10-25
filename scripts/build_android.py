"""Cloud build helper; Android Studio users can use the generated Gradle wrapper."""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path('/workspace/.tools')


def main():
    environment = dict(os.environ, JAVA_HOME=str(TOOLS / 'jdk-17.0.16+8'), ANDROID_HOME=str(TOOLS / 'android-sdk'),
                       ANDROID_USER_HOME=str(TOOLS / 'android-user'),
                       GRADLE_USER_HOME=str(TOOLS / 'gradle-cache'))
    proxy = urlparse(os.environ.get('HTTPS_PROXY', ''))
    options = []
    if proxy.hostname:
        for protocol in ('http', 'https'):
            options.extend([f'-D{protocol}.proxyHost={proxy.hostname}', f'-D{protocol}.proxyPort={proxy.port or 80}'])
    subprocess.run([str(TOOLS / 'gradle-8.13/bin/gradle'), '--no-daemon', *options,
                    'assembleDebug', 'lintDebug'], cwd=ROOT / 'image-summary/android',
                   env=environment, check=True)


if __name__ == '__main__':
    main()
