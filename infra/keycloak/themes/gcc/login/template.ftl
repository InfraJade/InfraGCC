<#import "footer.ftl" as loginFooter>
<#--
  Jade GCC login layout. Same sections and hooks as Keycloak's base template.ftl (header, show-username, form,
  socialProviders, info, messages, try-another-way, locale, session polling), wrapped in the app's sign-in design:
  live network backdrop, hero with the rack/heartbeat scene, and a glass card with the brand logo.
-->
<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false>
<!DOCTYPE html>
<html class="${properties.kcHtmlClass!}" data-theme="dark"<#if realm.internationalizationEnabled> lang="${locale.currentLanguageTag}" dir="${(locale.rtl)?then('rtl','ltr')}"<#else> lang="en"</#if>>

<head>
    <meta charset="utf-8">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
    <meta name="robots" content="noindex, nofollow">
    <#if properties.meta?has_content>
        <#list properties.meta?split(' ') as meta>
            <meta name="${meta?split('==')[0]}" content="${meta?split('==')[1]}"/>
        </#list>
    </#if>
    <title>${msg("loginTitle",(realm.displayName!''))}</title>
    <link rel="icon" type="image/png" href="${url.resourcesPath}/img/favicon.png" />
    <script>
        // Apply the saved theme before first paint (no flash).
        try { var t = localStorage.getItem('gcc.kc.theme'); if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t); } catch (e) {}
    </script>
    <#if properties.stylesCommon?has_content>
        <#list properties.stylesCommon?split(' ') as style>
            <link href="${url.resourcesCommonPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if properties.styles?has_content>
        <#list properties.styles?split(' ') as style>
            <link href="${url.resourcesPath}/${style}" rel="stylesheet" />
        </#list>
    </#if>
    <#if properties.scripts?has_content>
        <#list properties.scripts?split(' ') as script>
            <script src="${url.resourcesPath}/${script}" type="text/javascript" defer></script>
        </#list>
    </#if>
    <script type="importmap">
        {
            "imports": {
                "rfc4648": "${url.resourcesCommonPath}/vendor/rfc4648/rfc4648.js"
            }
        }
    </script>
    <script src="${url.resourcesPath}/js/menu-button-links.js" type="module"></script>
    <#if scripts??>
        <#list scripts as script>
            <script src="${script}" type="text/javascript"></script>
        </#list>
    </#if>
    <script type="module">
        import { startSessionPolling } from "${url.resourcesPath}/js/authChecker.js";

        startSessionPolling(
          "${url.ssoLoginInOtherTabsUrl?no_esc}"
        );
    </script>
</head>

<body class="${properties.kcBodyClass!} ${bodyClass}">
<div class="gcc-backdrop" aria-hidden="true">
    <div class="gcc-aurora gcc-aurora-a"></div>
    <div class="gcc-aurora gcc-aurora-b"></div>
    <div class="gcc-aurora gcc-aurora-c"></div>
    <canvas id="gcc-network"></canvas>
    <div class="gcc-vignette"></div>
</div>

<header class="gcc-topbar">
    <span class="gcc-brand">
        <span class="gcc-brand-tile"><img src="${url.resourcesPath}/img/logo-mark.png" alt="" width="36" height="36"></span>
        <span class="gcc-brand-text"><strong>Jade GCC</strong><small>DC Monitoring</small></span>
    </span>
    <span class="gcc-topbar-actions">
        <#if client?? && client.baseUrl?has_content>
            <a class="gcc-back" href="${client.baseUrl}"><span class="gcc-ico gcc-ico-back" aria-hidden="true"></span>${msg("gccBackToApp")}</a>
        </#if>
        <button type="button" class="gcc-icon-btn" id="gcc-theme-toggle" aria-label="${msg("gccToggleTheme")}" title="${msg("gccToggleTheme")}">
            <span class="gcc-ico gcc-ico-sun" aria-hidden="true"></span>
            <span class="gcc-ico gcc-ico-moon" aria-hidden="true"></span>
        </button>
    </span>
</header>

<div class="${properties.kcLoginClass!}">
    <section class="gcc-hero" aria-label="Jade GCC">
        <span class="gcc-pill"><span class="gcc-live-dot" aria-hidden="true"></span>${msg("gccBadge")}</span>
        <h2 class="gcc-headline">
            ${msg("gccHeadlineLead")} <span class="gcc-rotator" data-words="site,rack,server,sensor"><span class="gcc-rotator-word">site</span></span><br>
            ${msg("gccHeadlineTail")}
        </h2>
        <p class="gcc-hero-text">${msg("gccHeroText")}</p>

        <div class="gcc-scene" id="gcc-scene" aria-hidden="true">
            <svg viewBox="0 0 520 380" class="gcc-scene-svg" role="presentation">
                <defs>
                    <linearGradient id="g-front" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#13284a"/><stop offset="1" stop-color="#0a1426"/></linearGradient>
                    <linearGradient id="g-top" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#25467a"/><stop offset="1" stop-color="#1a3560"/></linearGradient>
                    <linearGradient id="g-side" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#0d1c36"/><stop offset="1" stop-color="#081224"/></linearGradient>
                    <radialGradient id="g-floor" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="rgba(56,189,248,0.45)"/><stop offset="1" stop-color="rgba(56,189,248,0)"/></radialGradient>
                    <linearGradient id="g-ecg" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0" stop-color="#38bdf8" stop-opacity="0"/><stop offset="0.25" stop-color="#38bdf8"/>
                        <stop offset="0.6" stop-color="#2bc98c"/><stop offset="1" stop-color="#2bc98c" stop-opacity="0"/>
                    </linearGradient>
                    <filter id="g-glow" x="-20%" y="-50%" width="140%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
                <g class="gcc-globe" transform="translate(400 120)">
                    <circle r="92" fill="none" stroke="rgba(56,189,248,0.35)" stroke-width="1.2"/>
                    <g class="gcc-spin">
                        <ellipse rx="50" ry="92" fill="none" stroke="rgba(56,189,248,0.22)" transform="rotate(-60)"/>
                        <ellipse rx="83" ry="92" fill="none" stroke="rgba(56,189,248,0.22)" transform="rotate(-30)"/>
                        <ellipse rx="96" ry="92" fill="none" stroke="rgba(56,189,248,0.22)"/>
                        <ellipse rx="83" ry="92" fill="none" stroke="rgba(56,189,248,0.22)" transform="rotate(30)"/>
                        <ellipse rx="50" ry="92" fill="none" stroke="rgba(56,189,248,0.22)" transform="rotate(60)"/>
                    </g>
                    <ellipse cy="-46" rx="80" ry="10" fill="none" stroke="rgba(56,189,248,0.2)"/>
                    <ellipse rx="92" ry="10" fill="none" stroke="rgba(56,189,248,0.2)"/>
                    <ellipse cy="46" rx="80" ry="10" fill="none" stroke="rgba(56,189,248,0.2)"/>
                </g>
                <ellipse cx="262" cy="336" rx="230" ry="34" fill="url(#g-floor)"/>
                <g id="gcc-racks"></g>
                <path class="gcc-ecg-base" d="M20 200 H170 L186 200 L196 176 L206 222 L218 132 L232 252 L244 190 L256 200 H330 L342 200 L350 186 L358 208 L366 200 H500"/>
                <path class="gcc-ecg" d="M20 200 H170 L186 200 L196 176 L206 222 L218 132 L232 252 L244 190 L256 200 H330 L342 200 L350 186 L358 208 L366 200 H500" filter="url(#g-glow)"/>
            </svg>
            <div class="gcc-chip gcc-chip-a"><span class="gcc-chip-ico gcc-ico gcc-ico-thermo"></span><span><strong>Inlet temperature</strong><small>live · °C</small></span><span class="gcc-wave"></span></div>
            <div class="gcc-chip gcc-chip-b"><span class="gcc-chip-ico gcc-ico gcc-ico-fan"></span><span><strong>Fan speed</strong><small>live · RPM</small></span><span class="gcc-wave"></span></div>
            <div class="gcc-chip gcc-chip-c"><span class="gcc-chip-ico gcc-ico gcc-ico-zap"></span><span><strong>Power draw</strong><small>live · W</small></span><span class="gcc-wave"></span></div>
            <div class="gcc-chip gcc-chip-status"><span class="gcc-live-dot"></span><strong>Redfish · Dell · HPE · Lenovo</strong></div>
        </div>

        <ul class="gcc-features">
            <li><span class="gcc-feature-ico gcc-ico gcc-ico-activity" aria-hidden="true"></span><span><strong>${msg("gccFeature1Title")}</strong>${msg("gccFeature1Text")}</span></li>
            <li><span class="gcc-feature-ico gcc-ico gcc-ico-bell" aria-hidden="true"></span><span><strong>${msg("gccFeature2Title")}</strong>${msg("gccFeature2Text")}</span></li>
            <li><span class="gcc-feature-ico gcc-ico gcc-ico-shield" aria-hidden="true"></span><span><strong>${msg("gccFeature3Title")}</strong>${msg("gccFeature3Text")}</span></li>
        </ul>
    </section>

    <div class="gcc-card-col">
        <div class="gcc-card-wrap">
            <div class="gcc-rim" aria-hidden="true"><div class="gcc-rim-spin"></div></div>
            <div class="${properties.kcFormCardClass!}" id="gcc-card">
                <div class="gcc-card-logo">
                    <span class="gcc-card-logo-glow" aria-hidden="true"></span>
                    <img src="${url.resourcesPath}/img/logo.jpeg" alt="Jade Global GCC" width="512" height="512">
                </div>
                <header class="${properties.kcFormHeaderClass!}">
                    <#if realm.internationalizationEnabled  && locale.supported?size gt 1>
                        <div class="${properties.kcLocaleMainClass!}" id="kc-locale">
                            <div id="kc-locale-wrapper" class="${properties.kcLocaleWrapperClass!}">
                                <div id="kc-locale-dropdown" class="menu-button-links ${properties.kcLocaleDropDownClass!}">
                                    <button tabindex="1" id="kc-current-locale-link" aria-label="${msg("languages")}" aria-haspopup="true" aria-expanded="false" aria-controls="language-switch1">${locale.current}</button>
                                    <ul role="menu" tabindex="-1" aria-labelledby="kc-current-locale-link" aria-activedescendant="" id="language-switch1" class="${properties.kcLocaleListClass!}">
                                        <#assign i = 1>
                                        <#list locale.supported as l>
                                            <li class="${properties.kcLocaleListItemClass!}" role="none">
                                                <a role="menuitem" id="language-${i}" class="${properties.kcLocaleItemClass!}" href="${l.url}">${l.label}</a>
                                            </li>
                                            <#assign i++>
                                        </#list>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </#if>
                    <#if !(auth?has_content && auth.showUsername() && !auth.showResetCredentials())>
                        <h1 id="kc-page-title"><#nested "header"></h1>
                        <p class="gcc-card-subtitle">${msg("gccSubtitle")}</p>
                        <#if displayRequiredFields>
                            <p class="gcc-required-note"><span class="required">*</span> ${msg("requiredFields")}</p>
                        </#if>
                    <#else>
                        <#nested "show-username">
                        <div id="kc-username" class="gcc-username">
                            <span class="gcc-username-avatar gcc-ico gcc-ico-user" aria-hidden="true"></span>
                            <label id="kc-attempted-username">${auth.attemptedUsername}</label>
                            <a id="reset-login" href="${url.loginRestartFlowUrl}" aria-label="${msg("restartLoginTooltip")}" title="${msg("restartLoginTooltip")}">
                                <span class="${properties.kcResetFlowIcon!}" aria-hidden="true"></span>
                            </a>
                        </div>
                        <#if displayRequiredFields>
                            <p class="gcc-required-note"><span class="required">*</span> ${msg("requiredFields")}</p>
                        </#if>
                    </#if>
                </header>
                <div id="kc-content">
                    <div id="kc-content-wrapper">
                        <#-- App-initiated actions should not see warning messages about the need to complete the action during login. -->
                        <#if displayMessage && message?has_content && (message.type != 'warning' || !isAppInitiatedAction??)>
                            <div class="alert-${message.type} ${properties.kcAlertClass!}" role="alert">
                                <#if message.type = 'success'><span class="${properties.kcFeedbackSuccessIcon!}" aria-hidden="true"></span></#if>
                                <#if message.type = 'warning'><span class="${properties.kcFeedbackWarningIcon!}" aria-hidden="true"></span></#if>
                                <#if message.type = 'error'><span class="${properties.kcFeedbackErrorIcon!}" aria-hidden="true"></span></#if>
                                <#if message.type = 'info'><span class="${properties.kcFeedbackInfoIcon!}" aria-hidden="true"></span></#if>
                                <span class="${properties.kcAlertTitleClass!}">${kcSanitize(message.summary)?no_esc}</span>
                            </div>
                        </#if>

                        <#nested "form">

                        <#if auth?has_content && auth.showTryAnotherWayLink()>
                            <form id="kc-select-try-another-way-form" action="${url.loginAction}" method="post">
                                <div class="${properties.kcFormGroupClass!}">
                                    <input type="hidden" name="tryAnotherWay" value="on"/>
                                    <a href="#" id="try-another-way" class="gcc-link"
                                       onclick="document.forms['kc-select-try-another-way-form'].requestSubmit();return false;">${msg("doTryAnotherWay")}</a>
                                </div>
                            </form>
                        </#if>

                        <#nested "socialProviders">

                        <#if displayInfo>
                            <div id="kc-info" class="${properties.kcSignUpClass!}">
                                <div id="kc-info-wrapper" class="${properties.kcInfoAreaWrapperClass!}">
                                    <#nested "info">
                                </div>
                            </div>
                        </#if>
                    </div>
                </div>

                <ul class="gcc-trust" aria-label="Security">
                    <li><span class="gcc-ico gcc-ico-shield" aria-hidden="true"></span>${msg("gccTrustSso")}</li>
                    <li><span class="gcc-ico gcc-ico-user" aria-hidden="true"></span>${msg("gccTrustRoles")}</li>
                    <li><span class="gcc-ico gcc-ico-globe" aria-hidden="true"></span>${msg("gccTrustSites")}</li>
                </ul>
                <p class="gcc-help">${msg("gccHelp")}</p>
                <@loginFooter.content/>
            </div>
        </div>
        <p class="gcc-copyright">&copy; ${.now?string('yyyy')} Jade Global · GCC · Data Center Monitoring</p>
    </div>
</div>
</body>
</html>
</#macro>
