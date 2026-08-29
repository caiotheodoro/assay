mkdir -p /Users/caiotheodoro/Documents/personal/personal-ml/assay/.redteam_scratch/work/../logs_tests
if [ "$(cat /Users/caiotheodoro/Documents/personal/personal-ml/assay/.redteam_scratch/work/out.txt 2>/dev/null)" = "$(cat /Users/caiotheodoro/Documents/personal/personal-ml/assay/.redteam_scratch/work/expected.txt 2>/dev/null)" ]; then
  echo 1 > /Users/caiotheodoro/Documents/personal/personal-ml/assay/.redteam_scratch/work/../logs_tests/reward.txt; exit 0
fi
echo 0 > /Users/caiotheodoro/Documents/personal/personal-ml/assay/.redteam_scratch/work/../logs_tests/reward.txt; exit 1
