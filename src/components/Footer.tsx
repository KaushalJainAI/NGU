import { Link } from "react-router-dom";
import { Mail, Phone, MapPin } from "lucide-react";
import { useTranslation } from "react-i18next";

const Footer = () => {
  const { t } = useTranslation();
  return (
    <footer className="bg-card border-t border-border mt-20 pb-20 md:pb-0">
      <div className="container mx-auto px-3 sm:px-4 py-6 sm:py-12">
        <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-8">
          {/* Company Info */}
          <div className="col-span-2 sm:col-span-1">
            <h3 className="notranslate text-base sm:text-xl font-bold text-primary mb-2 sm:mb-4">
              Nidhi Grah Udyog
            </h3>
            <p className="text-muted-foreground text-xs sm:text-base mb-2 sm:mb-4">
              {t('footer.tagline')}
            </p>
            {/* Social icons removed until the accounts exist.
                facebook.nidhimasala.com / instagram.nidhimasala.com are
                registrar forwarding records pointing at facebook.com and
                instagram.com *root* — no profile path. Facebook root hits a
                login wall, and Instagram root renders the VISITOR's own feed,
                which is why the link looked like "the wrong account".
                To restore: drop the real profile URLs into SOCIAL_LINKS. */}
          </div>

          {/* Quick Links */}
          <div>
            <h4 className="font-semibold text-foreground text-sm sm:text-base mb-2 sm:mb-4">{t('footer.quickLinks')}</h4>
            <ul className="space-y-1 sm:space-y-2 text-xs sm:text-base">
              <li>
                <Link to="/" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('nav.home')}
                </Link>
              </li>
              <li>
                <Link to="/products" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('nav.products')}
                </Link>
              </li>
              <li>
                <Link to="/about" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('nav.aboutUs')}
                </Link>
              </li>
              <li>
                <Link to="/contact" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('footer.contactUs')}
                </Link>
              </li>
            </ul>
          </div>

          {/* Customer Service */}
          <div>
            <h4 className="font-semibold text-foreground text-sm sm:text-base mb-2 sm:mb-4">{t('footer.customerService')}</h4>
            <ul className="space-y-1 sm:space-y-2 text-xs sm:text-base">
              <li>
                <Link to="/my-orders" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('nav.myOrders')}
                </Link>
              </li>
              <li>
                <Link to="/shipping-policy" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('footer.shippingPolicy')}
                </Link>
              </li>
              <li>
                <Link to="/return-policy" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('footer.returnPolicy')}
                </Link>
              </li>
              <li>
                <Link to="/privacy-policy" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('footer.privacyPolicy')}
                </Link>
              </li>
              <li>
                <Link to="/terms" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('footer.terms')}
                </Link>
              </li>
              <li>
                <Link to="/faq" className="text-muted-foreground hover:text-primary transition-colors">
                  {t('footer.faqs')}
                </Link>
              </li>
            </ul>
          </div>

          {/* Contact Info */}
          <div className="col-span-2 sm:col-span-1">
            <h4 className="font-semibold text-foreground text-sm sm:text-base mb-2 sm:mb-4">{t('footer.contactDetail')}</h4>
            <ul className="space-y-1 sm:space-y-3 text-xs sm:text-base">
              <li className="notranslate hidden sm:flex items-start space-x-3 text-muted-foreground">
                <MapPin className="h-5 w-5 mt-0.5 flex-shrink-0" />
                <span>7, Industrial Area, Runija Road, Barnagar. PIN-456771 <br />
                      Ujjain, MP, India</span>
              </li>
              <li className="notranslate flex items-center space-x-2 sm:space-x-3 text-muted-foreground">
                <Phone className="h-3 w-3 sm:h-5 sm:w-5 flex-shrink-0" />
                <span>+91 93000 05040</span>
              </li>
              <li className="notranslate flex items-center space-x-2 sm:space-x-3 text-muted-foreground">
                <Mail className="h-3 w-3 sm:h-5 sm:w-5 flex-shrink-0" />
                <a href="mailto:nidhispicesandfood@gmail.com" className="hover:text-primary transition-colors break-all">nidhispicesandfood@gmail.com</a>
              </li>
            </ul>
          </div>
        </div>

        <div className="border-t border-border mt-4 sm:mt-8 pt-4 sm:pt-8 text-center text-muted-foreground text-xs sm:text-base space-y-1">
          <p className="notranslate">
            Nidhi Grah Udyog (Proprietor: Lalit Kumar Jain) &bull;{" "}
            <a
              href="/gst-registration-certificate.pdf"
              target="_blank"
              rel="noopener noreferrer"
              className="underline decoration-dotted hover:text-primary transition-colors"
            >
              GSTIN: 23ABUPJ8925C1ZI
            </a>{" "}
            &bull;{" "}
            <a
              href="/fssai-license.pdf"
              target="_blank"
              rel="noopener noreferrer"
              className="underline decoration-dotted hover:text-primary transition-colors"
            >
              FSSAI Lic. No: 11414730000288
            </a>
          </p>
          <p>&copy; {new Date().getFullYear()} <span className="notranslate">Nidhi Grah Udyog</span>. {t('footer.rights')}</p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;

