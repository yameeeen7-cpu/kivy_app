[app]
title = My Application
package.name = myapp
package.domain = org.test

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 0.1
requirements = python3,kivy==2.2.1

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
android.accept_sdk_license = True

p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 0
