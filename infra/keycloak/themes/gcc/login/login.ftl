<#import "template.ftl" as layout>
<#--
  Username/password form. Same fields, names, ids and error handling as Keycloak's base login.ftl (the e2e tests
  and password managers rely on #username, #password, #kc-login), restyled with field icons and a submit button
  that shows progress.
-->
<@layout.registrationLayout displayMessage=!messagesPerField.existsError('username','password') displayInfo=realm.password && realm.registrationAllowed && !registrationDisabled??; section>
    <#if section = "header">
        ${msg("loginAccountTitle")}
    <#elseif section = "form">
        <div id="kc-form">
          <div id="kc-form-wrapper">
            <#if realm.password>
                <form id="kc-form-login" class="${properties.kcFormClass!}" onsubmit="login.disabled = true; this.classList.add('gcc-submitting'); return true;" action="${url.loginAction}" method="post" novalidate>
                    <#if !usernameHidden??>
                        <div class="${properties.kcFormGroupClass!}<#if messagesPerField.existsError('username','password')> ${properties.kcFormGroupErrorClass!}</#if>">
                            <label for="username" class="${properties.kcLabelClass!}"><#if !realm.loginWithEmailAllowed>${msg("username")}<#elseif !realm.registrationEmailAsUsername>${msg("usernameOrEmail")}<#else>${msg("email")}</#if></label>
                            <div class="gcc-input-shell">
                                <span class="gcc-input-ico gcc-ico gcc-ico-user" aria-hidden="true"></span>
                                <input tabindex="2" id="username" class="${properties.kcInputClass!}" name="username" value="${(login.username!'')}" type="text" autofocus autocomplete="username"
                                       aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                                       <#if messagesPerField.existsError('username','password')>aria-describedby="input-error"</#if>
                                       dir="ltr"
                                />
                            </div>
                            <#if messagesPerField.existsError('username','password')>
                                <span id="input-error" class="${properties.kcInputErrorMessageClass!}" aria-live="polite">
                                    <span class="gcc-ico gcc-ico-error" aria-hidden="true"></span>
                                    ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
                                </span>
                            </#if>
                        </div>
                    </#if>

                    <div class="${properties.kcFormGroupClass!}<#if messagesPerField.existsError('username','password')> ${properties.kcFormGroupErrorClass!}</#if>">
                        <label for="password" class="${properties.kcLabelClass!}">${msg("password")}</label>
                        <div class="gcc-input-shell ${properties.kcInputGroup!}" dir="ltr">
                            <span class="gcc-input-ico gcc-ico gcc-ico-lock" aria-hidden="true"></span>
                            <input tabindex="3" id="password" class="${properties.kcInputClass!}" name="password" type="password" autocomplete="current-password"
                                   aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>"
                            />
                            <button class="${properties.kcFormPasswordVisibilityButtonClass!}" type="button" aria-label="${msg("showPassword")}"
                                    aria-controls="password" data-password-toggle tabindex="4"
                                    data-icon-show="${properties.kcFormPasswordVisibilityIconShow!}" data-icon-hide="${properties.kcFormPasswordVisibilityIconHide!}"
                                    data-label-show="${msg('showPassword')}" data-label-hide="${msg('hidePassword')}">
                                <i class="${properties.kcFormPasswordVisibilityIconShow!}" aria-hidden="true"></i>
                            </button>
                        </div>
                        <p class="gcc-capslock" id="gcc-capslock" hidden><span class="gcc-ico gcc-ico-warning" aria-hidden="true"></span>Caps Lock is on</p>
                        <#if usernameHidden?? && messagesPerField.existsError('username','password')>
                            <span id="input-error" class="${properties.kcInputErrorMessageClass!}" aria-live="polite">
                                <span class="gcc-ico gcc-ico-error" aria-hidden="true"></span>
                                ${kcSanitize(messagesPerField.getFirstError('username','password'))?no_esc}
                            </span>
                        </#if>
                    </div>

                    <#if (realm.rememberMe && !usernameHidden??) || realm.resetPasswordAllowed>
                        <div class="gcc-options">
                            <#if realm.rememberMe && !usernameHidden??>
                                <label class="gcc-check">
                                    <input tabindex="5" id="rememberMe" name="rememberMe" type="checkbox" class="gcc-check-input" <#if login.rememberMe??>checked</#if>>
                                    <span>${msg("rememberMe")}</span>
                                </label>
                            <#else>
                                <span></span>
                            </#if>
                            <#if realm.resetPasswordAllowed>
                                <a tabindex="6" class="gcc-link" href="${url.loginResetCredentialsUrl}">${msg("doForgotPassword")}</a>
                            </#if>
                        </div>
                    </#if>

                    <div id="kc-form-buttons" class="${properties.kcFormGroupClass!}">
                        <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>/>
                        <button tabindex="7" class="${properties.kcButtonClass!} ${properties.kcButtonPrimaryClass!} ${properties.kcButtonBlockClass!} ${properties.kcButtonLargeClass!}" name="login" id="kc-login" type="submit" value="${msg("doLogIn")}">
                            <span class="gcc-btn-sheen" aria-hidden="true"></span>
                            <span class="gcc-btn-spinner" aria-hidden="true"></span>
                            <span class="gcc-btn-label">${msg("doLogIn")}</span>
                            <span class="gcc-ico gcc-ico-arrow" aria-hidden="true"></span>
                        </button>
                    </div>
                </form>
            </#if>
          </div>
        </div>
        <script type="module" src="${url.resourcesPath}/js/passwordVisibility.js"></script>
    <#elseif section = "info" >
        <#if realm.password && realm.registrationAllowed && !registrationDisabled??>
            <div id="kc-registration-container">
                <div id="kc-registration">
                    <span>${msg("noAccount")} <a tabindex="8" class="gcc-link" href="${url.registrationUrl}">${msg("doRegister")}</a></span>
                </div>
            </div>
        </#if>
    <#elseif section = "socialProviders" >
        <#if realm.password && social?? && social.providers?has_content>
            <div id="kc-social-providers" class="${properties.kcFormSocialAccountSectionClass!}">
                <p class="gcc-divider"><span>${msg("identity-provider-login-label")}</span></p>
                <ul class="${properties.kcFormSocialAccountListClass!}">
                    <#list social.providers as p>
                        <li>
                            <a id="social-${p.alias}" class="${properties.kcFormSocialAccountListButtonClass!}" type="button" href="${p.loginUrl}">
                                <span class="${properties.kcFormSocialAccountNameClass!}">${p.displayName!}</span>
                            </a>
                        </li>
                    </#list>
                </ul>
            </div>
        </#if>
    </#if>
</@layout.registrationLayout>
