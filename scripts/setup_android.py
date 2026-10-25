"""Install verified Android/Gradle tools into /workspace/.tools (no system changes)."""
import hashlib
import os
import subprocess
import xml.etree.ElementTree as ET
import zipfile
import tarfile
import shutil
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse

TOOLS = Path('/workspace/.tools')
TOOLS.mkdir(exist_ok=True)


def download(url, target, digest, algorithm='sha256'):
    if target.exists() and hashlib.new(algorithm, target.read_bytes()).hexdigest() == digest:
        return
    temporary = target.with_suffix('.part')
    hasher = hashlib.new(algorithm)
    with urlopen(url, timeout=60) as source, temporary.open('wb') as dest:
        while block := source.read(1024 * 1024):
            hasher.update(block)
            dest.write(block)
    if hasher.hexdigest() != digest:
        temporary.unlink()
        raise RuntimeError('Official artifact checksum mismatch')
    temporary.replace(target)


def main():
    jdk_url = 'https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.16%2B8/OpenJDK17U-jdk_x64_linux_hotspot_17.0.16_8.tar.gz'
    with urlopen(jdk_url + '.sha256.txt', timeout=30) as response:
        digest = response.read().decode().split()[0]
    jdk_archive = TOOLS / 'jdk17.tar.gz'
    download(jdk_url, jdk_archive, digest)
    jdk = TOOLS / 'jdk-17.0.16+8'
    if not (jdk / 'bin/javac').exists():
        with tarfile.open(jdk_archive) as bundle:
            bundle.extractall(TOOLS, filter='data')
    # Preserve TLS verification using the machine's managed CA trust store.
    system_trust = Path('/etc/ssl/certs/java/cacerts')
    if system_trust.is_file():
        shutil.copyfile(system_trust, jdk / 'lib/security/cacerts')
    gradle_url = 'https://services.gradle.org/distributions/gradle-8.13-bin.zip'
    with urlopen(gradle_url + '.sha256', timeout=30) as response:
        digest = response.read().decode().strip()
    archive = TOOLS / 'gradle-8.13-bin.zip'
    download(gradle_url, archive, digest)
    if not (TOOLS / 'gradle-8.13/bin/gradle').exists():
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(TOOLS)
        (TOOLS / 'gradle-8.13/bin/gradle').chmod(0o755)
    sdk = TOOLS / 'android-sdk'
    sdk.mkdir(exist_ok=True)
    manager = sdk / 'cmdline-tools/12.0/bin/sdkmanager'
    if not manager.exists():
        with urlopen('https://dl.google.com/android/repository/repository2-1.xml', timeout=30) as response:
            root = ET.fromstring(response.read())
        selected = None
        for package in root.findall('remotePackage'):
            if package.get('path') == 'cmdline-tools;12.0':
                for item in package.findall('archives/archive'):
                    if item.findtext('host-os') == 'linux':
                        selected = item.find('complete')
                        break
        if selected is None:
            raise RuntimeError('Official Android command line tools metadata missing')
        checksum = selected.find('checksum')
        archive = TOOLS / 'android-commandline-tools.zip'
        download('https://dl.google.com/android/repository/' + selected.findtext('url'),
                 archive, checksum.text, checksum.get('type', 'sha1'))
        unpack = TOOLS / 'android-unpack'
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(unpack)
        (sdk / 'cmdline-tools').mkdir(exist_ok=True)
        (unpack / 'cmdline-tools').rename(sdk / 'cmdline-tools/12.0')
        for executable in (sdk / 'cmdline-tools/12.0/bin').iterdir():
            executable.chmod(0o755)
    environment = dict(os.environ, JAVA_HOME=str(jdk), ANDROID_HOME=str(sdk), ANDROID_USER_HOME=str(TOOLS / 'android-user'),
                       GRADLE_USER_HOME=str(TOOLS / 'gradle-cache'))
    proxy = urlparse(os.environ.get('HTTPS_PROXY', ''))
    if proxy.hostname:
        options = f'-Dhttps.proxyHost={proxy.hostname} -Dhttps.proxyPort={proxy.port or 80} -Dhttp.proxyHost={proxy.hostname} -Dhttp.proxyPort={proxy.port or 80}'
        environment['JAVA_TOOL_OPTIONS'] = os.environ.get('JAVA_TOOL_OPTIONS', '') + ' ' + options
    subprocess.run([str(manager), '--sdk_root=' + str(sdk), '--licenses'], input='y\n' * 100,
                   text=True, check=True, env=environment)
    subprocess.run([str(manager), '--sdk_root=' + str(sdk), 'platforms;android-35',
                    'build-tools;35.0.0', 'platform-tools'], check=True, env=environment)
    print('Verified Android SDK and Gradle installed in', TOOLS)


if __name__ == '__main__':
    main()
