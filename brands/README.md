# Brand assets

The same three images live in two places, because HACS accepts either and they do
different jobs.

```
custom_components/maxa_advantix/brand/     <- shipped with the integration
brands/custom_integrations/maxa_advantix/  <- for the pull request below
├── icon.png      256 x 256
└── icon@2x.png   512 x 512
```

There is no `logo.png`, and that is deliberate. The brands guidance says that when
the logo would be the same image as the icon, only the icon should be submitted, and
the icon is used as the logo's fallback. A square 512 x 512 logo would fail their
size rule anyway, which wants the shortest side between 128 and 256 pixels.

**The in-repository copy** is what HACS checks first. Its validation looks for
`custom_components/<domain>/brand/icon.png` and only falls back to the brands
repository when that is missing. Shipping it means the HACS check passes on day one
rather than waiting in someone else's review queue, which is the difference between
being submittable now and being submittable eventually.

**The copy under `brands/`** is for a pull request to
[home-assistant/brands](https://github.com/home-assistant/brands). That is what puts
the icon in the Home Assistant UI itself, for every user, rather than only in the
HACS listing. Worth doing, just not worth blocking on.

Regenerate both with `python scripts/make_icon.py`.

## Submitting them

Custom integrations go under `custom_integrations/`, not `core_integrations/`.
The directory name must be the integration domain exactly.

```bash
gh repo fork home-assistant/brands --clone --remote
cd brands
git switch -c add-maxa-advantix
mkdir -p custom_integrations/maxa_advantix
cp /path/to/hass-maxa-advantix/brands/custom_integrations/maxa_advantix/*.png \
   custom_integrations/maxa_advantix/
git add custom_integrations/maxa_advantix
git commit -m "Add MAXA / Advantix heat pump"
git push -u origin add-maxa-advantix
gh pr create --repo home-assistant/brands \
  --title "Add MAXA / Advantix heat pump (custom integration)" \
  --body "Icon for the maxa_advantix custom integration: https://github.com/gcoutinho-ipca/hass-maxa-advantix"
```

## About the artwork

The design is deliberately **not** derived from the manufacturer's visual
identity, and is not their logo. It is a three-blade fan over a cold-to-warm
gradient: the fan because it is the universal shorthand for an outdoor unit, and
the gradient because these machines are reversible.

Using a manufacturer's logo in a third-party integration is a trademark question
nobody needs, and this project is not affiliated with MAXA. If MAXA ever wants
their own mark used here, that is their call to make and their file to provide.
