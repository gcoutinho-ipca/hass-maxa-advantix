# Brand assets

These files exist for one purpose: HACS requires an entry in
[home-assistant/brands](https://github.com/home-assistant/brands) before an
integration can be listed in the default store, and without it the integration
shows a generic placeholder in the Home Assistant UI.

```
brands/custom_integrations/maxa_advantix/
├── icon.png      256 x 256
├── icon@2x.png   512 x 512
└── logo.png      512 x 512
```

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
  --body "Icon and logo for the maxa_advantix custom integration: https://github.com/gcoutinho-ipca/hass-maxa-advantix"
```

## About the artwork

The design is deliberately **not** derived from the manufacturer's visual
identity, and is not their logo. It is a three-blade fan over a cold-to-warm
gradient: the fan because it is the universal shorthand for an outdoor unit, and
the gradient because these machines are reversible.

Using a manufacturer's logo in a third-party integration is a trademark question
nobody needs, and this project is not affiliated with MAXA. If MAXA ever wants
their own mark used here, that is their call to make and their file to provide.

Regenerated with `scripts/make_icon.py`.
