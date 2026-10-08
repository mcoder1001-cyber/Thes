#!/bin/bash
# D1 set-up on the box: build the jar with the CRaC JDK (release 21), extract it into Spring
# Boot's layout (application jar + lib/, which the AOT cache can use; a nested fat jar it can't).
set -euo pipefail
cd "$(dirname "$0")/app"
JAVA_HOME=/opt/crac mvn -q -B package -DskipTests
rm -rf /var/tmp/d1/app && mkdir -p /var/tmp/d1
/opt/crac/bin/java -Djarmode=tools -jar target/craca.jar extract --destination /var/tmp/d1/app
ls -la /var/tmp/d1/app
