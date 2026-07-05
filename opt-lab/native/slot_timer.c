/* FT8 slot timing — zero-GIL seconds_until_tx_period */
#include <math.h>

#define CYCLE_SECONDS 15.0
#define MAX_TX_START 2.5

static int ft8_period(double t) {
  double m = fmod(t, 30.0);
  if (m < 0) m += 30.0;
  return (int)(m / 15.0);
}

double seconds_until_tx_period(int want, double now) {
  int p = ft8_period(now);
  double in_slot = fmod(now, CYCLE_SECONDS);
  if (in_slot < 0) in_slot += CYCLE_SECONDS;
  if (p == want && in_slot <= MAX_TX_START) return 0.0;
  if (p == want) return 30.0 - fmod(now, 30.0);
  return CYCLE_SECONDS - in_slot;
}
