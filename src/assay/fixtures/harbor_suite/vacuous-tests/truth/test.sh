mkdir -p /logs/verifier
if [ "$(cat /work/out.txt 2>/dev/null)" = "42" ]; then
  echo 1 > /logs/verifier/reward.txt; exit 0
fi
echo 0 > /logs/verifier/reward.txt; exit 1
